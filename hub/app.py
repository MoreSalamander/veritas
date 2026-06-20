"""The Hub control plane — FastAPI over the real engine.

Endpoints serve Mission Control, runs, and institutional memory from real data. A
run is executed synchronously (fine for local single-user; a queue is a hosted
concern). The model defaults to local Ollama; swap via VERITAS_MODEL / the provider
seam. Static UI is served at /.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.artifact import Artifact
from engine.memory import MemoryStore
from engine.model import ClaudeProvider, ModelProvider, OllamaProvider
from engine.run import ActivityEntry, set_activity_listener
from hub.store import RunStore, summarize
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
    "qwen": {"label": "Qwen3.5 9B · local ★", "cost": "free", "kind": "ollama", "id": "qwen3.5:9b", "think": False},
    "gemma-12b": {"label": "Gemma 12B · local", "cost": "free", "kind": "ollama", "id": "gemma4:12b", "think": False},
    "qwen-64k": {"label": "Qwen3.5 64k · local · thinking", "cost": "free", "kind": "ollama", "id": "qwen3.5-64k:latest", "think": True},
    "llama": {"label": "Llama3.1 8B · local", "cost": "free", "kind": "ollama", "id": "llama3.1:8b", "think": False},
    "haiku": {"label": "Claude Haiku", "cost": "~1–3¢/build", "kind": "claude", "id": "claude-haiku-4-5", "think": False},
    "sonnet": {"label": "Claude Sonnet", "cost": "~4–8¢/build", "kind": "claude", "id": "claude-sonnet-4-6", "think": False},
    "opus": {"label": "Claude Opus", "cost": "~6–13¢/build", "kind": "claude", "id": "claude-opus-4-8", "think": False},
}

DEFAULT_MODEL = "qwen"


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

    def web_profile_store() -> ProfileStore:
        return ProfileStore(base / "profiles" / "web.json")

    def _event(entry: ActivityEntry) -> dict[str, Any]:
        return {
            "phase": entry.phase.value,
            "actor": entry.actor,
            "message": entry.message,
            "duration_ms": round(entry.duration_ms, 1),
            "at": entry.at,
        }

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

    return app


app = create_app()
