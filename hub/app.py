"""The Hub control plane — FastAPI over the real engine.

Endpoints serve Mission Control, runs, and institutional memory from real data. A
run is executed synchronously (fine for local single-user; a queue is a hosted
concern). The model defaults to local Ollama; swap via VERITAS_MODEL / the provider
seam. Static UI is served at /.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.memory import MemoryStore
from engine.model import ClaudeProvider, ModelProvider, OllamaProvider
from hub.store import RunStore, summarize
from orgs.registry import REGISTRY, get_org

# The model toggle: local (free) plus the three Claude tiers. Reliability comes from the
# gates regardless of which proposes — this just lets you discover which model a build needs.
MODELS: dict[str, dict[str, str]] = {
    "local": {"label": "Local · llama3.1:8b", "cost": "free", "claude_id": ""},
    "haiku": {"label": "Claude Haiku", "cost": "~1–3¢/build", "claude_id": "claude-haiku-4-5"},
    "sonnet": {"label": "Claude Sonnet", "cost": "~4–8¢/build", "claude_id": "claude-sonnet-4-6"},
    "opus": {"label": "Claude Opus", "cost": "~6–13¢/build", "claude_id": "claude-opus-4-8"},
}


def _provider_for(model: str) -> ModelProvider:
    if model == "local":
        return OllamaProvider(model=os.environ.get("VERITAS_MODEL", "llama3.1:8b"))
    spec = MODELS.get(model)
    if not spec or not spec["claude_id"]:
        raise ValueError(f"unknown model {model!r}")
    return ClaudeProvider(spec["claude_id"])

# Anchor the data dir to the repo root, NOT the launch directory, so the hub finds the
# same runs no matter where it's started from. (Relative "./hub_data" silently moved the
# data when the server was launched from a different cwd.) VERITAS_DATA overrides it.
_ROOT = Path(__file__).resolve().parent.parent
_DATA = Path(os.environ.get("VERITAS_DATA", str(_ROOT / "hub_data")))
_STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    goal: str
    org: str = "software"
    model: str = "local"


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

    app = FastAPI(title="Veritas Hub")

    @app.get("/api/orgs")
    def list_orgs() -> list[dict[str, str]]:
        return [
            {
                "name": org.name,
                "title": org.title,
                "description": org.description,
                "input_noun": org.input_noun,
                "produces": org.produces,
                "verified_by": org.verified_by,
                "goal_hint": org.goal_hint,
            }
            for org in REGISTRY.values()
        ]

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

    @app.post("/api/runs")
    def create_run(req: RunRequest) -> dict[str, Any]:
        org = get_org(req.org)  # KeyError -> 500 is acceptable locally; UI only offers known orgs
        try:
            prov = injected_provider or _provider_for(req.model)
            result = org.build(req.goal, prov, org_memory(org.name))
        except Exception as exc:  # missing API key, unknown model, model API error
            return {"error": f"{type(exc).__name__}: {exc}"}
        summary = summarize(result, datetime.now(timezone.utc).isoformat(), model=req.model)
        runs.save(summary)
        return runs.get(summary.id) or {}

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
        return FileResponse(_STATIC / "index.html")

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    return app


app = create_app()
