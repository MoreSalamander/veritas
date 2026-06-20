"""The Hub control plane — FastAPI over the real engine.

Endpoints serve Mission Control, runs, and institutional memory from real data. A
run is executed synchronously (fine for local single-user; a queue is a hosted
concern). The model defaults to local Ollama; swap via VERITAS_MODEL / the provider
seam. Static UI is served at /.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.artifact import Artifact
from engine.memory import MemoryStore
from engine.model import ClaudeProvider, ModelProvider, OllamaProvider
from engine.run import ActivityEntry, set_activity_listener
from hub.store import RunStore, summarize
from orgs.production_studio.assets import SayGenerator, StubGenerator
from orgs.production_studio.pipeline import ProductionResult
from orgs.production_studio.publishing import (
    FfmpegPublisher,
    Publisher,
    PublishProfile,
    parse_publish,
)
from orgs.production_studio.taste import (
    ProductionProfileStore,
    Review as ProdReview,
    build_create_production,
)
from orgs.registry import REGISTRY, get_org
from orgs.web_studio.aesthetics import aesthetic_gates
from orgs.web_studio.browser import RenderResult
from orgs.web_studio.create import Review, build_create_page
from orgs.web_studio.gates import RenderGate, StructureGate
from orgs.web_studio.interview import CreateSpec, interview
from orgs.web_studio.profile import ProfileStore, apply_profile, profile_hint

# The model toggle: local Ollama models (free) plus the three Claude tiers. Reliability comes
# from the gates regardless of which model proposes — this just lets you discover which model a
# build needs. Each entry declares its kind ("ollama" | "claude"), the exact id, and whether to
# run with reasoning ON. `think` pairs with context: qwen3.5:9b runs think-off (fast, direct);
# qwen3.5-64k has the context headroom to reason AND still answer, so it runs think-on.
class ModelSpec(TypedDict):
    label: str
    cost: str
    kind: str  # "ollama" | "claude"
    id: str
    think: bool


MODELS: dict[str, ModelSpec] = {
    "gemma-12b": {"label": "Gemma 12B · local ★", "cost": "free", "kind": "ollama", "id": "gemma4:12b", "think": False},
    "qwen": {"label": "Qwen3.5 9B · local", "cost": "free", "kind": "ollama", "id": "qwen3.5:9b", "think": False},
    "qwen-64k": {"label": "Qwen3.5 64k · local · thinking", "cost": "free", "kind": "ollama", "id": "qwen3.5-64k:latest", "think": True},
    "llama": {"label": "Llama3.1 8B · local", "cost": "free", "kind": "ollama", "id": "llama3.1:8b", "think": False},
    "haiku": {"label": "Claude Haiku", "cost": "~1–3¢/build", "kind": "claude", "id": "claude-haiku-4-5", "think": False},
    "sonnet": {"label": "Claude Sonnet", "cost": "~4–8¢/build", "kind": "claude", "id": "claude-sonnet-4-6", "think": False},
    "opus": {"label": "Claude Opus", "cost": "~6–13¢/build", "kind": "claude", "id": "claude-opus-4-8", "think": False},
}

DEFAULT_MODEL = "gemma-12b"


def _provider_for(model: str) -> ModelProvider:
    spec = MODELS.get(model)
    if spec is None:
        raise ValueError(f"unknown model {model!r}")
    if spec["kind"] == "ollama":
        # reasoning runs generate far more tokens, so give them a longer leash
        return OllamaProvider(
            model=spec["id"], think=spec["think"], timeout=600.0 if spec["think"] else 120.0
        )
    return ClaudeProvider(spec["id"])

# Anchor the data dir to the repo root, NOT the launch directory, so the hub finds the
# same runs no matter where it's started from. (Relative "./hub_data" silently moved the
# data when the server was launched from a different cwd.) VERITAS_DATA overrides it.
_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from .env into the environment (without overriding anything already
    set). Without this the Claude models are in the toggle but unusable when the hub is launched
    plainly — the SDK can't find ANTHROPIC_API_KEY. Stdlib only; no python-dotenv dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(_ROOT / ".env")
_DATA = Path(os.environ.get("VERITAS_DATA", str(_ROOT / "hub_data")))
_STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    goal: str
    org: str = "software"
    model: str = DEFAULT_MODEL
    sources: list[str] = []  # pinned corpus for orgs that need it (Research); ignored otherwise


class CreateStartRequest(BaseModel):
    goal: str
    model: str = DEFAULT_MODEL


class AnswerBody(BaseModel):
    answer: str


class ReviewBody(BaseModel):
    approved: bool
    feedback: str = ""


class ProduceRequest(BaseModel):
    brief: str
    model: str = DEFAULT_MODEL
    voice: str | None = None  # macOS `say` voice for the narration; None = default voice


class RouteRequest(BaseModel):
    request: str
    model: str = DEFAULT_MODEL


# Deterministic fallback if the model-routed pick fails: first keyword group that matches wins.
_ROUTE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("video", "film", "animation", "movie", "trailer", "narrat", "explainer"), "production"),
    (("lesson", "teach", "course", "curriculum", "学"), "education"),
    (("article", "news", "newsroom", "story about"), "newsroom"),
    (("report", "grounded", "cite", "sources", "summari"), "research"),
    (("experiment", "hypothesis", "benchmark", "reproduc", "outperform", "whether", " beat "), "empirical"),
    (("startup", "mvp", "business", "profitable"), "startup"),
    (("roguelike", "game ", "rpg", "platformer"), "game"),
    (("page", "website", "landing", "site", "html", "dashboard", "ui "), "web"),
    (("function", "code", "module", "algorithm", "program", "script", "app "), "software"),
]


def _keyword_route(request: str) -> str:
    r = f" {request.lower()} "
    for kws, org in _ROUTE_KEYWORDS:
        if any(k in r for k in kws):
            return org
    return "software"


_VOICES_CACHE: list[dict[str, str]] | None = None


def available_voices() -> list[dict[str, str]]:
    """English macOS `say` voices as [{name, locale}]. Empty off macOS. Cached (the listing is slow)."""
    global _VOICES_CACHE
    if _VOICES_CACHE is not None:
        return _VOICES_CACHE
    voices: list[dict[str, str]] = []
    if shutil.which("say"):
        try:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                if "#" not in line:
                    continue
                toks = line.split("#")[0].split()
                if len(toks) >= 2 and toks[-1].startswith("en"):
                    voices.append({"name": " ".join(toks[:-1]), "locale": toks[-1]})
        except (OSError, subprocess.SubprocessError):
            voices = []
    _VOICES_CACHE = voices
    return voices


def _event(entry: ActivityEntry) -> dict[str, Any]:
    return {
        "phase": entry.phase.value,
        "actor": entry.actor,
        "message": entry.message,
        "duration_ms": round(entry.duration_ms, 1),
        "at": entry.at,
    }


def _production_video_url(result: ProductionResult | None) -> str | None:
    """Derive the served URL for a production's rendered output (last two path segments under
    /productions), if it reached the publish stage."""
    if result is None:
        return None
    for o in result.outcomes:
        if o.artifact.type == "publish":
            try:
                parts = [p for p in parse_publish(o.artifact.payload).output.split("/") if p]
            except Exception:
                return None
            if len(parts) >= 2:
                return "/productions/" + "/".join(parts[-2:])
    return None


def _production_trust(result: ProductionResult | None) -> list[dict[str, Any]]:
    """The machine floor as a flat trust list — every gate verdict across every stage."""
    rows: list[dict[str, Any]] = []
    if result is None:
        return rows
    for o in result.outcomes:
        for g in o.artifact.provenance.gate_results:
            rows.append({"stage": o.artifact.type, "gate": g.gate_name,
                         "determinism": g.determinism.value, "passed": g.passed,
                         "evidence": g.evidence})
    return rows


def _production_findings(result: ProductionResult | None) -> list[dict[str, str]]:
    """When the chain is refused, the failing hard gates (last verdict per gate, minus validation)."""
    if result is None:
        return []
    last: dict[str, str] = {}
    for o in result.outcomes:
        for g in o.artifact.provenance.gate_results:
            if not g.passed and g.determinism.value == "hard" and g.gate_name != "validation":
                last[g.gate_name] = g.evidence
    return [{"gate": k, "evidence": v} for k, v in last.items()]


def _spec_dict(spec: CreateSpec) -> dict[str, Any]:
    a = spec.aesthetics
    return {
        "title": spec.title,
        "description": spec.description,
        "required_elements": spec.required_elements,
        "aesthetics": {
            "theme": a.theme, "min_contrast": a.min_contrast,
            "fonts": a.fonts, "palette": a.palette,
        },
    }


def _create_trust(rendered: RenderResult, spec: CreateSpec) -> dict[str, Any]:
    """The three-tier trust map for a create-mode candidate. The MACHINE tier re-derives the
    declared hard gates over the (already-computed) render — pure functions, no re-render — so the
    UI shows exactly which facts were machine-proven. Create mode has no model-judge gate (the
    aesthetic residue is the human's call), so the MODEL tier is empty by design and the HUMAN tier
    is the pending Approve. Nothing is shown as more verified than it is."""
    throwaway = Artifact.propose(type="page", owner="hub", payload="", rationale="", parent_id="")
    gates = [RenderGate(rendered), StructureGate(rendered, spec.required_elements),
             *aesthetic_gates(rendered, spec.aesthetics)]
    machine = []
    for g in gates:
        r = g.check(throwaway)
        machine.append({"name": g.name, "passed": r.passed, "evidence": r.evidence})
    return {"machine": machine, "model": [], "human": "pending"}


class CreateSession:
    """Drives the unchanged create-mode engine (interview -> build_create_page) from a background
    thread. The engine's `answer` and `review` callbacks block on threading Events; the human
    supplies them over HTTP, so a synchronous local loop becomes a turn-based web conversation
    without forking any engine logic. Single-user/local: one daemon thread per session."""

    def __init__(self, token: str, goal: str, model: str, provider: ModelProvider,
                 memory: MemoryStore, profile_store: ProfileStore) -> None:
        self.token = token
        self.goal = goal
        self.provider = provider
        self.memory = memory
        self.profile_store = profile_store
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {
            "phase": "interviewing", "goal": goal, "model": model,
            "question": None, "transcript": [], "spec": None,
            "page_html": None, "trust": None, "iteration": 0,
            "result": None, "error": None,
        }
        self._answer = threading.Event()
        self._answer_val = ""
        self._review = threading.Event()
        self._review_val = Review(False)

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            s = dict(self.state)
            s["transcript"] = [list(qa) for qa in self.state["transcript"]]
            return s

    def provide_answer(self, answer: str) -> None:
        self._answer_val = answer
        self._answer.set()

    def provide_review(self, approved: bool, feedback: str) -> None:
        self._review_val = Review(approved, feedback)
        self._review.set()

    def _set(self, **fields: Any) -> None:
        with self.lock:
            self.state.update(fields)

    def _answer_fn(self, question: str) -> str:
        self._set(phase="interviewing", question=question)
        self._answer.wait()
        self._answer.clear()
        ans = self._answer_val
        with self.lock:
            self.state["transcript"].append([question, ans])
            self.state["question"] = None
            self.state["phase"] = "building"
        return ans

    def _review_fn(self, html: str, rendered: RenderResult, spec: CreateSpec) -> Review:
        trust = _create_trust(rendered, spec)
        with self.lock:
            self.state["iteration"] += 1
            self.state["page_html"] = html
            self.state["trust"] = trust
            self.state["phase"] = "reviewing"
        self._review.wait()
        self._review.clear()
        self._set(phase="building")
        return self._review_val

    def _run(self) -> None:
        try:
            known = profile_hint(self.profile_store.load())
            result = interview(self.goal, self.provider, self._answer_fn, known=known)
            if result.spec is None:
                self._set(phase="done",
                          error="couldn't reach a gateable spec within the interview budget")
                return
            # apply the learned profile here too, so the trust report reflects the same filled
            # spec the engine gates against (apply_profile only fills UNSET fields — idempotent).
            spec = apply_profile(self.profile_store.load(), result.spec)
            self._set(spec=_spec_dict(spec), phase="building")
            built = build_create_page(
                spec, self.provider, self.memory,
                review=lambda html, r: self._review_fn(html, r, spec),
                profile_store=self.profile_store,
            )
            # When the floor is never met, the user deserves to know WHICH gate refused and why
            # (e.g. an unsatisfiable palette/contrast combo). The activity log carries every
            # verdict; keep the last failing verdict per gate so the UI can show it.
            findings: list[dict[str, str]] = []
            if not built.machine_verified:
                last: dict[str, str] = {}
                for e in built.activity:
                    if e.message.startswith("FAIL:") and e.actor != "validation":
                        last[e.actor] = e.message[len("FAIL:"):].strip()
                findings = [{"gate": g, "evidence": ev} for g, ev in last.items()]
            self._set(
                phase="done",
                # always show the page — the approved one if it shipped, else the last rejected
                # candidate, so the gate findings are grounded in something you can actually see.
                page_html=(built.page_outcome.artifact.payload if built.page_outcome
                           else (built.last_page_html or None)),
                result={
                    "accepted": built.accepted,
                    "machine_verified": built.machine_verified,
                    "iterations": built.iterations,
                    "run_id": built.run_id,
                    "memory_path": (str(built.page_outcome.memory_path)
                                    if built.page_outcome else None),
                    "findings": findings,
                },
            )
        except Exception as exc:  # model error, render failure, missing key
            self._set(phase="done", error=f"{type(exc).__name__}: {exc}")


class ProductionCreateSession:
    """Create mode for a production. Runs the whole chain (the machine floor); when it ships, a human
    judges the cut over HTTP (the review callback blocks on an Event). Approve → human-approved record
    + the style profile compounds; request changes → the brief is amended and it re-runs."""

    def __init__(self, token: str, brief: str, model: str, provider: ModelProvider,
                 memory: MemoryStore, productions_root: Path, profile_store: ProductionProfileStore,
                 publisher: Publisher | None, voice: str | None = None) -> None:
        self.token = token
        self.brief = brief
        self.provider = provider
        self.memory = memory
        self.work = productions_root / uuid4().hex
        self.profile_store = profile_store
        self.publisher = publisher
        self.voice = voice
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {
            "phase": "producing", "brief": brief, "model": model, "events": [],
            "video_url": None, "trust": None, "iteration": 0, "result": None, "error": None,
        }
        self._review = threading.Event()
        self._review_val = ProdReview(False)

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.state)

    def provide_review(self, approved: bool, feedback: str) -> None:
        self._review_val = ProdReview(approved, feedback)
        self._review.set()

    def _set(self, **fields: Any) -> None:
        with self.lock:
            self.state.update(fields)

    def _review_fn(self, result: ProductionResult) -> ProdReview:
        with self.lock:
            self.state["iteration"] += 1
            self.state["video_url"] = _production_video_url(result)
            self.state["trust"] = _production_trust(result)
            self.state["phase"] = "reviewing"
        self._review.wait()
        self._review.clear()
        self._set(phase="producing")
        return self._review_val

    def _run(self) -> None:
        set_activity_listener(lambda e: self.state["events"].append(_event(e)))
        try:
            generator = SayGenerator(voice=self.voice) if shutil.which("say") else StubGenerator()  # real narration on macOS
            res = build_create_production(
                self.brief, self.provider, self.memory, review=self._review_fn,
                asset_generator=generator, publisher=self.publisher,
                profile=PublishProfile(), asset_dir=self.work,
                profile_store=self.profile_store, max_attempts=3,
            )
            self._set(
                phase="done",
                video_url=_production_video_url(res.production) if res.accepted else None,
                result={
                    "accepted": res.accepted,
                    "machine_verified": res.machine_verified,
                    "iterations": res.iterations,
                    "memory_path": res.memory_path,
                    "findings": [] if res.machine_verified else _production_findings(res.production),
                },
            )
        except Exception as exc:  # model error, ffmpeg failure, missing key
            self._set(phase="done", error=f"{type(exc).__name__}: {exc}")
        finally:
            set_activity_listener(None)


def create_app(
    data_dir: Path | None = None, provider: ModelProvider | None = None
) -> FastAPI:
    base = Path(data_dir) if data_dir else _DATA
    runs = RunStore(base / "runs")
    injected_provider = provider  # set in tests; when None, pick per-request by model

    # Each org keeps its own institutional memory: recall stays relevant to the
    # domain, and it mirrors how a hosted deployment would isolate tenants.
    memories: dict[str, MemoryStore] = {}

    def org_memory(org_name: str) -> MemoryStore:
        if org_name not in memories:
            memories[org_name] = MemoryStore(base / "memory" / org_name)
        return memories[org_name]

    # Live run state, keyed by a one-shot token, so the UI can watch a run unfold
    # (Explain -> Synthesize -> Verify -> Persist) instead of only seeing the result.
    progress: dict[str, dict[str, Any]] = {}

    # Create-mode sessions (the interview/build conversation), keyed by token.
    create_sessions: dict[str, CreateSession] = {}
    produce_sessions: dict[str, ProductionCreateSession] = {}

    def web_profile_store() -> ProfileStore:
        return ProfileStore(base / "profiles" / "web.json")

    def production_profile_store() -> ProductionProfileStore:
        return ProductionProfileStore(base / "profiles" / "production.json")

    app = FastAPI(title="Veritas Hub")

    @app.get("/api/orgs")
    def list_orgs() -> list[dict[str, Any]]:
        return [
            {
                "name": org.name,
                "title": org.title,
                "description": org.description,
                "input_noun": org.input_noun,
                "produces": org.produces,
                "verified_by": org.verified_by,
                "goal_hint": org.goal_hint,
                "needs_sources": org.needs_sources,
            }
            for org in REGISTRY.values()
        ]

    @app.get("/api/orgs/{name}/roster")
    def org_roster(name: str) -> dict[str, Any]:
        org = REGISTRY.get(name)
        if org is None or org.roster is None:
            return {"error": "no roster for this org"}
        return org.roster()

    @app.post("/api/route")
    def route(req: RouteRequest) -> dict[str, Any]:
        """The front door: a model proposes which studio a request belongs to (and a concise goal);
        a deterministic keyword pass is the fallback. The UI shows the proposal for the human to
        confirm before anything runs — routing is a proposal, the gates are still the authority."""
        studios = "; ".join(f"{o.name} = {o.description}" for o in REGISTRY.values())
        system = (
            "You route a user's request to exactly one studio, and extract a concise goal for it. "
            f"Studios: {studios}. Reply with ONLY JSON: "
            "{\"org\": \"<studio name>\", \"goal\": \"<a concise goal/brief for that studio>\"}."
        )
        org: str | None = None
        goal = req.request.strip()
        try:
            prov = injected_provider or _provider_for(req.model)
            raw = prov.propose(role="router", prompt=req.request, system=system)
            start, end = raw.find("{"), raw.rfind("}")
            obj = json.loads(raw[start:end + 1]) if 0 <= start < end else {}
            cand = str(obj.get("org", "")).strip()
            if cand in REGISTRY:
                org = cand
                goal = str(obj.get("goal") or req.request).strip()
        except Exception:  # model down/parse fail -> deterministic fallback
            org = None
        if org is None:
            org = _keyword_route(req.request)
        o = REGISTRY[org]
        return {"org": org, "title": o.title, "goal": goal,
                "produces": o.produces, "needs_sources": o.needs_sources}

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        all_runs = runs.list()
        accepted = sum(1 for r in all_runs if r.get("accepted"))
        mem = [m for org_name in REGISTRY for m in org_memory(org_name).load_all()]
        rate = (accepted / len(all_runs) * 100.0) if all_runs else 0.0
        return {
            "total_runs": len(all_runs),
            "accepted_runs": accepted,
            "success_rate": round(rate, 1),
            "memory_entries": len(mem),
            "failures": sum(1 for m in mem if m.category == "failure"),
            "by_org": {
                org_name: sum(1 for r in all_runs if r.get("org") == org_name)
                for org_name in REGISTRY
            },
            "recent": all_runs[:8],
        }

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return runs.list()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        found = runs.get(run_id)
        return found or {"error": "not found"}

    @app.get("/api/models")
    def list_models() -> list[dict[str, str]]:
        return [{"name": k, "label": v["label"], "cost": v["cost"]} for k, v in MODELS.items()]

    @app.post("/api/runs/start")
    def start_run(req: RunRequest) -> dict[str, str]:
        """Kick off a run in the background and return a token to watch it by. The build
        is unchanged — it just runs under a listener that streams its activity into
        `progress[token]`, which the timeline polls."""
        token = uuid4().hex
        progress[token] = {
            "events": [
                {
                    "phase": "explain",
                    "actor": "run",
                    "message": "run started — the cast is proposing…",
                    "duration_ms": 0.0,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "done": False,
            "run": None,
            "error": None,
        }

        def worker() -> None:
            set_activity_listener(lambda e: progress[token]["events"].append(_event(e)))
            try:
                org = get_org(req.org)
                prov = injected_provider or _provider_for(req.model)
                result = org.build(req.goal, prov, org_memory(org.name), sources=req.sources)
                summary = summarize(result, datetime.now(timezone.utc).isoformat(), model=req.model)
                runs.save(summary)
                progress[token]["run"] = runs.get(summary.id)
            except Exception as exc:  # missing key, unknown model/org, model API error
                progress[token]["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                progress[token]["done"] = True
                set_activity_listener(None)

        threading.Thread(target=worker, daemon=True).start()
        return {"token": token}

    @app.get("/api/runs/progress/{token}")
    def run_progress(token: str) -> dict[str, Any]:
        state = progress.get(token)
        if state is None:
            return {"error": "unknown run token"}
        return state

    @app.post("/api/runs")
    def create_run(req: RunRequest) -> dict[str, Any]:
        org = get_org(req.org)  # KeyError -> 500 is acceptable locally; UI only offers known orgs
        try:
            prov = injected_provider or _provider_for(req.model)
            result = org.build(req.goal, prov, org_memory(org.name), sources=req.sources)
        except Exception as exc:  # missing API key, unknown model, model API error
            return {"error": f"{type(exc).__name__}: {exc}"}
        summary = summarize(result, datetime.now(timezone.utc).isoformat(), model=req.model)
        runs.save(summary)
        return runs.get(summary.id) or {}

    # --- Create mode: verify=gate, create=annotate. The interview manufactures the checkable
    # criteria, the machine proves what it can, the human is the gate for feel. First home: Web. ---

    @app.post("/api/create/start")
    def create_start(req: CreateStartRequest) -> dict[str, str]:
        token = uuid4().hex
        prov = injected_provider or _provider_for(req.model)
        sess = CreateSession(token, req.goal, req.model, prov,
                             org_memory("web"), web_profile_store())
        create_sessions[token] = sess
        sess.start()
        return {"token": token}

    @app.get("/api/create/{token}")
    def create_state(token: str) -> dict[str, Any]:
        sess = create_sessions.get(token)
        return sess.snapshot() if sess else {"error": "unknown create session"}

    @app.post("/api/create/{token}/answer")
    def create_answer(token: str, body: AnswerBody) -> dict[str, Any]:
        sess = create_sessions.get(token)
        if sess is None:
            return {"error": "unknown create session"}
        sess.provide_answer(body.answer)
        return {"ok": True}

    @app.post("/api/create/{token}/review")
    def create_review(token: str, body: ReviewBody) -> dict[str, Any]:
        sess = create_sessions.get(token)
        if sess is None:
            return {"error": "unknown create session"}
        sess.provide_review(body.approved, body.feedback)
        return {"ok": True}

    @app.get("/api/profile/web")
    def web_profile() -> dict[str, Any]:
        p = web_profile_store().load()
        return {
            "approvals": p.approvals,
            "theme": p.theme(),
            "theme_votes": p.theme_votes,
            "palette": p.palette,
            "fonts": p.fonts,
            "min_contrast": p.min_contrast,
        }

    # --- Production create mode: run the chain, the human approves the cut, the style profile learns.

    @app.post("/api/produce/start")
    def produce_start(req: ProduceRequest) -> dict[str, str]:
        token = uuid4().hex
        prov = injected_provider or _provider_for(req.model)
        publisher: Publisher | None = (
            FfmpegPublisher() if shutil.which("ffmpeg") and shutil.which("ffprobe") else None
        )
        sess = ProductionCreateSession(
            token, req.brief, req.model, prov, org_memory("production"),
            base / "productions", production_profile_store(), publisher, voice=req.voice,
        )
        produce_sessions[token] = sess
        sess.start()
        return {"token": token}

    @app.get("/api/voices")
    def list_voices() -> list[dict[str, str]]:
        return available_voices()

    @app.get("/api/voices/{voice}/sample.wav")
    def voice_sample(voice: str) -> FileResponse:
        # validate against the real voice list (the name also goes to `say` as an argv arg, never a shell)
        if voice not in {v["name"] for v in available_voices()}:
            raise HTTPException(status_code=404, detail="unknown voice")
        samples = base / "voice_samples"
        samples.mkdir(parents=True, exist_ok=True)
        path = samples / f"{re.sub(r'[^A-Za-z0-9_-]', '_', voice)}.wav"
        if not path.exists():
            subprocess.run(
                ["say", "-v", voice, "-o", str(path), "--data-format=LEI16@22050",
                 f"Hi, I'm {voice}. Here's how your narration will sound."],
                check=True, capture_output=True, timeout=30,
            )
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "max-age=86400"})

    @app.get("/api/produce/{token}")
    def produce_state(token: str) -> dict[str, Any]:
        sess = produce_sessions.get(token)
        return sess.snapshot() if sess else {"error": "unknown produce session"}

    @app.post("/api/produce/{token}/review")
    def produce_review(token: str, body: ReviewBody) -> dict[str, Any]:
        sess = produce_sessions.get(token)
        if sess is None:
            return {"error": "unknown produce session"}
        sess.provide_review(body.approved, body.feedback)
        return {"ok": True}

    @app.get("/api/profile/production")
    def production_profile() -> dict[str, Any]:
        p = production_profile_store().load()
        return {"approvals": p.approvals, "tone": p._top(p.tone_votes),
                "resolution": p._top(p.resolution_votes), "hint": p.hint()}

    @app.get("/api/memory")
    def list_memory() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for org_name in REGISTRY:
            for m in org_memory(org_name).load_all():
                out.append(
                    {
                        "id": m.id,
                        "org": org_name,
                        "category": m.category,
                        "title": m.title,
                        "tags": m.tags,
                        "body": m.body,
                        "file": f"memory/{org_name}/{'failures' if m.category == 'failure' else 'institutional'}/{m.id}.md",
                        "created_at": m.created_at,
                        "informed_by": m.provenance.get("informed_by", []),
                        "accepted_because": m.provenance.get("accepted_because"),
                        "rejected_because": m.provenance.get("rejected_because"),
                    }
                )
        out.sort(key=lambda m: str(m["created_at"]), reverse=True)
        return out

    @app.get("/")
    def index() -> FileResponse:
        # Never cache the shell: the UI iterates fast and a stale index is pure confusion.
        return FileResponse(_STATIC / "index.html", headers={"Cache-Control": "no-store"})

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    # Serve rendered productions (images + the published video) so the UI can play them.
    productions = base / "productions"
    productions.mkdir(parents=True, exist_ok=True)
    app.mount("/productions", StaticFiles(directory=productions), name="productions")

    return app


app = create_app()
