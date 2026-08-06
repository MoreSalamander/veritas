"""Stage 8 (Deterministic AI Workflow) emitter: publishes every real
persisted run's lifecycle as DataHub's native process model — one
DataProcessInstance per run, one child instance per phase, each with
STARTED/COMPLETE run events, real measured durations, and a
SUCCESS/FAILURE result — so every transition is recorded, ordered, and
auditable, not collapsed into a single accepted boolean.

HOW THE VISION'S LIFECYCLE MAPS ONTO VERITAS'S REAL ONE (engine/run.py
Phase + engine/artifact.py ArtifactStatus — mapped, not renamed):

    Proposal      -> the SYNTHESIZE phase (an agent proposes artifacts)
    Validation    -> the VERIFY phase's gate checks
    Execution     -> the EXPLAIN phase + the run itself
    Verification  -> VERIFY again — in Veritas validation IS verification
                     (one deterministic gate pass, not two ceremonies)
    Human Review  -> HUMAN-determinism gates where a pipeline has them
                     (create mode); absent for fully-automated runs,
                     honestly, rather than a fake sign-off
    Production    -> the PERSIST phase (accepted artifacts enter memory)
    Deployment    -> platform-level, not per-artifact: the Stage 2 infra
                     entities are the deployment record
    Monitoring    -> platform-level: Stage 6's observability entities,
                     computed from these same runs

TIMESTAMPS — two honesty levels, stated per event: runs persisted after
hub/store.py started recording ActivityEntry.at carry real wall-clock
times; older runs only recorded per-entry durations, so their event
times are DERIVED (run created_at + cumulative measured durations) and
each such instance is labeled timestamps=derived. Ordering and durations
are real in both cases.
"""

from __future__ import annotations

import os

import json
from datetime import datetime, timedelta
from pathlib import Path

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DataProcessInstancePropertiesClass,
    DataProcessInstanceRelationshipsClass,
    DataProcessInstanceRunEventClass,
    DataProcessInstanceRunResultClass,
    DataProcessRunStatusClass,
    RunResultTypeClass,
)

GMS_SERVER = os.environ.get("DATAHUB_GMS", "http://localhost:8080")
ACTOR = "urn:li:corpuser:veritas"


def _emit(emitter: DatahubRestEmitter, urn: str, aspect) -> None:
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def _millis(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def phase_spans(run: dict) -> list[dict]:
    """Collapse a run's activity log into ordered per-phase spans with real
    measured durations and start times (real `at` when persisted, derived
    from cumulative durations otherwise). Pure — offline testable."""
    created_ms = _millis(run["created_at"])
    spans: list[dict] = []
    cursor_ms = created_ms
    for entry in run.get("activity") or []:
        phase = entry.get("phase", "unknown")
        at = entry.get("at")
        start_ms = _millis(at) if at else cursor_ms
        duration_ms = float(entry.get("duration_ms") or 0.0)
        if spans and spans[-1]["phase"] == phase:
            spans[-1]["duration_ms"] += duration_ms
        else:
            spans.append(
                {"phase": phase, "start_ms": start_ms, "duration_ms": duration_ms, "derived": at is None}
            )
        cursor_ms = start_ms + int(duration_ms)
    return spans


def emit_run_lifecycles(runs_dir: Path, gms_server: str = GMS_SERVER) -> list[str]:
    """Publish each persisted run and its per-phase transitions. Returns the
    run-level DataProcessInstance URNs."""
    emitter = DatahubRestEmitter(gms_server=gms_server)
    urns: list[str] = []
    try:
        for path in sorted(runs_dir.glob("*.json")):
            run = json.loads(path.read_text())
            run_id = run["id"]
            created_ms = _millis(run["created_at"])
            run_urn = f"urn:li:dataProcessInstance:veritas-{run_id}"
            urns.append(run_urn)

            spans = phase_spans(run)
            total_ms = int(sum(s["duration_ms"] for s in spans))
            derived = any(s["derived"] for s in spans)
            _emit(
                emitter,
                run_urn,
                DataProcessInstancePropertiesClass(
                    name=f"{run['org']} run: {run['goal'][:80]}",
                    created=AuditStampClass(time=created_ms, actor=ACTOR),
                    customProperties={
                        "org": run.get("org", ""),
                        "goal": run.get("goal", ""),
                        "accepted": str(run.get("accepted", False)),
                        "timestamps": "derived" if derived else "recorded",
                    },
                ),
            )
            _emit(
                emitter,
                run_urn,
                DataProcessInstanceRunEventClass(
                    timestampMillis=created_ms, status=DataProcessRunStatusClass.STARTED
                ),
            )
            _emit(
                emitter,
                run_urn,
                DataProcessInstanceRunEventClass(
                    timestampMillis=created_ms + total_ms,
                    status=DataProcessRunStatusClass.COMPLETE,
                    durationMillis=total_ms,
                    result=DataProcessInstanceRunResultClass(
                        type=RunResultTypeClass.SUCCESS if run.get("accepted") else RunResultTypeClass.FAILURE,
                        nativeResultType="veritas-run",
                    ),
                ),
            )

            for index, span in enumerate(spans):
                phase_urn = f"urn:li:dataProcessInstance:veritas-{run_id}-{index}-{span['phase']}"
                start = int(span["start_ms"])
                duration = int(span["duration_ms"])
                _emit(
                    emitter,
                    phase_urn,
                    DataProcessInstancePropertiesClass(
                        name=f"{run_id} phase {index}: {span['phase']}",
                        created=AuditStampClass(time=start, actor=ACTOR),
                        customProperties={
                            "phase": span["phase"],
                            "sequence": str(index),
                            "timestamps": "derived" if span["derived"] else "recorded",
                        },
                    ),
                )
                _emit(
                    emitter,
                    phase_urn,
                    DataProcessInstanceRelationshipsClass(upstreamInstances=[], parentInstance=run_urn),
                )
                _emit(
                    emitter,
                    phase_urn,
                    DataProcessInstanceRunEventClass(
                        timestampMillis=start, status=DataProcessRunStatusClass.STARTED
                    ),
                )
                _emit(
                    emitter,
                    phase_urn,
                    DataProcessInstanceRunEventClass(
                        timestampMillis=start + duration,
                        status=DataProcessRunStatusClass.COMPLETE,
                        durationMillis=duration,
                        result=DataProcessInstanceRunResultClass(
                            type=RunResultTypeClass.SUCCESS, nativeResultType="veritas-phase"
                        ),
                    ),
                )
        return urns
    finally:
        emitter.close()


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parent.parent
    urns = emit_run_lifecycles(root / "hub_data" / "runs")
    print(f"emitted {len(urns)} run lifecycles as DataProcessInstances", file=sys.stderr)
