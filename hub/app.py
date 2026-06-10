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
from engine.model import ModelProvider, OllamaProvider
from hub.store import RunStore, summarize
from orgs.software_studio.pipeline import build_software

_DATA = Path(os.environ.get("VERITAS_DATA", "./hub_data"))
_STATIC = Path(__file__).parent / "static"


class RunRequest(BaseModel):
    goal: str


def create_app(
    data_dir: Path | None = None, provider: ModelProvider | None = None
) -> FastAPI:
    base = Path(data_dir) if data_dir else _DATA
    memory = MemoryStore(base / "memory")
    runs = RunStore(base / "runs")
    model: ModelProvider = provider or OllamaProvider(
        model=os.environ.get("VERITAS_MODEL", "llama3.1:8b")
    )

    app = FastAPI(title="Veritas Hub")

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        all_runs = runs.list()
        accepted = sum(1 for r in all_runs if r.get("accepted"))
        mem = memory.load_all()
        rate = (accepted / len(all_runs) * 100.0) if all_runs else 0.0
        return {
            "total_runs": len(all_runs),
            "accepted_runs": accepted,
            "success_rate": round(rate, 1),
            "memory_entries": len(mem),
            "failures": sum(1 for m in mem if m.category == "failure"),
            "recent": all_runs[:8],
        }

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return runs.list()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        found = runs.get(run_id)
        return found or {"error": "not found"}

    @app.post("/api/runs")
    def create_run(req: RunRequest) -> dict[str, Any]:
        result = build_software(req.goal, model, memory)
        summary = summarize(req.goal, result, datetime.now(timezone.utc).isoformat())
        runs.save(summary)
        return runs.get(summary.id) or {}

    @app.get("/api/memory")
    def list_memory() -> list[dict[str, Any]]:
        records = memory.load_all()
        records.sort(key=lambda m: m.created_at, reverse=True)
        return [
            {
                "id": m.id,
                "category": m.category,
                "title": m.title,
                "tags": m.tags,
                "created_at": m.created_at,
                "informed_by": m.provenance.get("informed_by", []),
                "accepted_because": m.provenance.get("accepted_because"),
                "rejected_because": m.provenance.get("rejected_because"),
            }
            for m in records
        ]

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    return app


app = create_app()
