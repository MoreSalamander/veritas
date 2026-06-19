"""Run history — real telemetry persisted per run.

Artifacts live in institutional/failure memory; this records the *run* that produced
them (goal, outcome, the cast's verdicts, timing, what memory informed it) so the
Hub can show Mission Control from real data. JSON-per-run on disk, mirroring the
file-per-record memory shape; a DB backend can slot behind the same interface when
hosted.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.run import Phase
from engine.tokens import estimate_tokens  # built by the org itself (bootstrap); now powers telemetry
from orgs.registry import OrgRun


@dataclass
class GateView:
    gate: str
    determinism: str
    passed: bool
    evidence: str


@dataclass
class ArtifactView:
    type: str
    owner: str
    status: str
    store: str  # "institutional" | "failures"
    file: str
    payload: str  # the actual content (the code, the documentation, the spec)


@dataclass
class ActivityView:
    phase: str
    actor: str
    message: str
    duration_ms: float


@dataclass
class RunSummary:
    id: str
    org: str
    model: str
    goal: str
    accepted: bool
    created_at: str
    informed_by: list[str]
    artifacts: list[ArtifactView]
    gates: list[GateView]
    activity: list[ActivityView]
    tokens_estimate: int = 0  # rough output size, via the org-built estimate_tokens


def summarize(result: OrgRun, created_at: str, model: str = "local") -> RunSummary:
    artifacts: list[ArtifactView] = []
    gates: list[GateView] = []
    for outcome in result.outcomes:
        art = outcome.artifact
        artifacts.append(
            ArtifactView(
                type=art.type,
                owner=art.owner,
                status=art.status.value,
                store=outcome.memory_path.parent.name,
                file=outcome.memory_path.name,
                payload=art.payload,
            )
        )
        for gr in art.provenance.gate_results:
            gates.append(
                GateView(
                    gate=gr.gate_name,
                    determinism=gr.determinism.value,
                    passed=gr.passed,
                    evidence=gr.evidence,
                )
            )
    activity = [
        ActivityView(
            phase=entry.phase.value if isinstance(entry.phase, Phase) else str(entry.phase),
            actor=entry.actor,
            message=entry.message,
            duration_ms=round(entry.duration_ms, 1),
        )
        for entry in result.activity
    ]
    return RunSummary(
        id=result.run_id,
        org=result.org,
        model=model,
        goal=result.goal,
        accepted=result.accepted,
        created_at=created_at,
        informed_by=result.informed_by,
        artifacts=artifacts,
        gates=gates,
        activity=activity,
        tokens_estimate=sum(estimate_tokens(a.payload) for a in artifacts),
    )


class RunStore:
    def __init__(self, base_path: Path | str) -> None:
        self.base = Path(base_path)
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, summary: RunSummary) -> Path:
        path = self.base / f"{summary.id}.json"
        path.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")
        return path

    def get(self, run_id: str) -> dict[str, Any] | None:
        path = self.base / f"{run_id}.json"
        if not path.exists():
            return None
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def list(self) -> list[dict[str, Any]]:
        runs = [json.loads(p.read_text(encoding="utf-8")) for p in self.base.glob("*.json")]
        runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return runs
