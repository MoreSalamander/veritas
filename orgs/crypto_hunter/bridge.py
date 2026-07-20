"""Crypto Hunter AI as a Veritas org — the external-org bridge.

Crypto Hunter is the first org that lives OUTSIDE this repo: its own codebase,
venv, models, and data (~/MoreSalamander/crypto-hunter). The bridge runs its
day-cycle as a subprocess and translates the results into Veritas's normal
currency — Artifacts carrying HARD GateResults, persisted to memory, returned
as an OrgRun. Nothing here re-judges anything: the org's own deterministic
scaffold gate produced the verdicts; the bridge only reports them.

Deliberately does NOT import crypto-hunter code (separate venv) — it reads the
org's DataHub (SQLite) directly, read-only.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4

from engine.artifact import Artifact, Determinism, GateResult
from engine.memory import MemoryRecord, MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Phase
from orgs.registry import OrgRun

CRYPTO_HUNTER_DIR = Path.home() / "MoreSalamander" / "crypto-hunter"
DATAHUB = CRYPTO_HUNTER_DIR / "data" / "datahub.sqlite3"

_STAGE_PHASE = {
    "sweeping": Phase.EXPLAIN,
    "beat": Phase.EXPLAIN,
    "verifier": Phase.SYNTHESIZE,
    "scam": Phase.SYNTHESIZE,
    "gate": Phase.VERIFY,
    "ranker": Phase.VERIFY,
    "debate": Phase.VERIFY,
}


def _phase_for(line: str) -> Phase:
    for key, phase in _STAGE_PHASE.items():
        if key in line:
            return phase
    return Phase.PERSIST


def run_crypto_hunter(
    goal: str,
    provider: ModelProvider,
    memory: MemoryStore,
    sources: list[str] | None = None,
) -> OrgRun:
    """Run the org's full day-cycle and report it as an OrgRun.

    `provider` is unused by design: the org brings its own models (its .env
    selects Claude for product runs, an OpenAI dev key for build runs)."""
    run_id = f"chrun_{uuid4().hex[:12]}"
    activity: list[ActivityEntry] = [
        ActivityEntry(
            phase=Phase.EXPLAIN,
            actor="crypto-hunter",
            message=f"day-cycle started (goal: {goal or 'daily hunt'})",
        )
    ]
    proc = subprocess.run(
        [str(CRYPTO_HUNTER_DIR / ".venv" / "bin" / "python"), "cli.py", "day", "--no-voice"],
        cwd=CRYPTO_HUNTER_DIR,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("=="):
            activity.append(
                ActivityEntry(
                    phase=_phase_for(line), actor="crypto-hunter", message=line.strip("= ")
                )
            )
    if proc.returncode != 0:
        activity.append(
            ActivityEntry(
                phase=Phase.COMPLETE,
                actor="crypto-hunter",
                message=f"day-cycle FAILED (exit {proc.returncode}): {proc.stderr[-400:]}",
            )
        )
        return OrgRun(
            org="crypto_hunter", goal=goal, accepted=False, outcomes=[],
            informed_by=[], run_id=run_id, activity=activity,
        )

    outcomes = _outcomes_from_datahub(memory)
    accepted = any(o.accepted for o in outcomes)
    activity.append(
        ActivityEntry(
            phase=Phase.COMPLETE,
            actor="crypto-hunter",
            message=(
                f"day-cycle complete: {sum(o.accepted for o in outcomes)} verified, "
                f"{sum(not o.accepted for o in outcomes)} rejected by the scaffold gate"
            ),
        )
    )
    return OrgRun(
        org="crypto_hunter", goal=goal, accepted=accepted, outcomes=outcomes,
        informed_by=[], run_id=run_id, activity=activity,
    )


def _outcomes_from_datahub(memory: MemoryStore) -> list[Outcome]:
    """Translate today's gated records into Veritas Outcomes. Each record's
    gate evidence becomes HARD GateResults — verdicts made by crypto-hunter's
    own deterministic gate, faithfully reported."""
    if not DATAHUB.exists():
        return []
    conn = sqlite3.connect(f"file:{DATAHUB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT spec_json FROM opportunities WHERE trust_status IN ('verified','rejected')"
            " ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()

    outcomes: list[Outcome] = []
    for (spec_json,) in rows:
        spec = json.loads(spec_json)
        artifact = Artifact.propose(
            type="opportunity",
            owner=spec.get("discovered_by", "crypto-hunter"),
            payload=spec_json,
            rationale=spec.get("summary") or spec.get("name", "opportunity"),
        )
        gate_results = [
            GateResult(
                gate_name=f"scaffold:{ev['check']}",
                determinism=Determinism.HARD,
                passed=bool(ev["passed"]),
                evidence=json.dumps(ev.get("data", {}))[:500],
            )
            for ev in spec.get("verification", [])
        ]
        for gr in gate_results:
            artifact.record_gate(gr)
        accepted = spec.get("trust_status") == "verified"
        if accepted:
            artifact.accept(because="all scaffold-gate checks passed with evidence")
            record = MemoryRecord.from_accepted_artifact(artifact)
        else:
            failed = ", ".join(g.gate_name for g in gate_results if not g.passed) or "gate"
            artifact.reject()
            record = MemoryRecord.from_rejected_artifact(artifact, reason=f"failed {failed}")
        memory_path = memory.persist(record)
        outcomes.append(
            Outcome(
                artifact=artifact,
                accepted=accepted,
                gate_results=gate_results,
                memory_path=memory_path,
            )
        )
    return outcomes
