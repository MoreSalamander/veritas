"""Stage 6 (Agent Observability) emitter: publishes per-agent operational
metrics computed from REAL run history — the hub's persisted runs
(hub_data/runs/*.json: every artifact's owner + status, every gate's
determinism + verdict, every activity entry's actor + duration_ms), the
wedge usage ledger (hub_data/usage.db, the billing/quota record), and
token estimates over each agent's actual outputs via engine.tokens.
estimate_tokens (the system's own self-built, gate-verified component).

Metrics per agent (an artifact owner, e.g. spec-agent/developer-agent):
    proposals / accepted / rejected  -> success & failure rate
    est_tokens_total                 -> token consumption (estimate_tokens
                                        over the agent's real payloads —
                                        an ESTIMATE, labeled as one)
    avg_latency_ms                   -> mean of the agent's real
                                        activity duration_ms entries

Per org: validation outcomes (gates passed/failed) and the
GATE-DETERMINISM DISTRIBUTION (hard/soft/human verdict counts) — this
system's honest replacement for both "hallucination frequency" and
"confidence distributions": a HARD gate cannot hallucinate by
construction, a SOFT gate's opinion is never disguised as fact, so the
meaningful observability question is what fraction of verdicts carry
which rigor — measurable, native to the architecture, not self-reported.

Operational cost: the wedge usage ledger (runs per tenant — the exact
record quota/billing decisions are made from). NOT emitted: resource
utilization (CPU/memory) — nothing in this stack measures it, and
publishing a made-up number would be fabrication; it can join the graph
when real measurement exists.
"""

from __future__ import annotations

import os

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SubTypesClass,
)

from engine.tokens import estimate_tokens

GMS_SERVER = os.environ.get("DATAHUB_GMS", "http://localhost:8080")
PLATFORM = "veritas"
OWNER_URN = "urn:li:corpGroup:veritas-observability"


def _emit(emitter: DatahubRestEmitter, urn: str, aspect) -> None:
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def compute_agent_metrics(runs_dir: Path) -> tuple[dict, dict]:
    """Aggregate per-agent and per-org metrics from the hub's real persisted
    runs. Returns (agents, orgs) — plain dicts, separately testable offline."""
    agents: dict[str, dict] = defaultdict(
        lambda: {"proposals": 0, "accepted": 0, "rejected": 0, "est_tokens": 0, "latencies": []}
    )
    orgs: dict[str, dict] = defaultdict(
        lambda: {
            "runs": 0,
            "runs_accepted": 0,
            "gates_passed": 0,
            "gates_failed": 0,
            "determinism": {"hard": 0, "soft": 0, "human": 0},
        }
    )
    for path in sorted(runs_dir.glob("*.json")):
        run = json.loads(path.read_text())
        org = orgs[run.get("org", "unknown")]
        org["runs"] += 1
        org["runs_accepted"] += 1 if run.get("accepted") else 0
        for gate in run.get("gates") or []:
            org["gates_passed" if gate.get("passed") else "gates_failed"] += 1
            determinism = gate.get("determinism", "")
            if determinism in org["determinism"]:
                org["determinism"][determinism] += 1
        for artifact in run.get("artifacts") or []:
            agent = agents[artifact.get("owner", "unknown")]
            agent["proposals"] += 1
            if artifact.get("status") == "accepted":
                agent["accepted"] += 1
            elif artifact.get("status") == "rejected":
                agent["rejected"] += 1
            agent["est_tokens"] += estimate_tokens(artifact.get("payload") or "")
        for entry in run.get("activity") or []:
            duration = entry.get("duration_ms")
            if duration:
                agents[entry.get("actor", "unknown")]["latencies"].append(duration)
    return dict(agents), dict(orgs)


def read_usage_ledger(usage_db: Path) -> list[tuple[str, int, int]]:
    """[(tenant, total_runs, accepted_runs)] from the wedge billing ledger."""
    if not usage_db.exists():
        return []
    conn = sqlite3.connect(f"file:{usage_db}?mode=ro", uri=True)
    try:
        return [
            (tenant, total, accepted)
            for tenant, total, accepted in conn.execute(
                "SELECT tenant, COUNT(*), SUM(accepted) FROM usage GROUP BY tenant"
            )
        ]
    finally:
        conn.close()


def emit_observability(
    runs_dir: Path,
    usage_db: Path,
    gms_server: str = GMS_SERVER,
) -> list[str]:
    agents, orgs = compute_agent_metrics(runs_dir)
    ledger = read_usage_ledger(usage_db)

    ownership = OwnershipClass(
        owners=[OwnerClass(owner=OWNER_URN, type=OwnershipTypeClass.DATAOWNER)]
    )
    emitter = DatahubRestEmitter(gms_server=gms_server)
    urns: list[str] = []
    try:
        for name, m in agents.items():
            urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},agent-{name},PROD)"
            urns.append(urn)
            decided = m["accepted"] + m["rejected"]
            latencies = m["latencies"]
            _emit(
                emitter,
                urn,
                DatasetPropertiesClass(
                    name=f"agent: {name}",
                    description=f"Operational metrics for {name}, computed from the hub's real persisted runs.",
                    customProperties={
                        "proposals": str(m["proposals"]),
                        "accepted": str(m["accepted"]),
                        "rejected": str(m["rejected"]),
                        "success_rate": f"{m['accepted'] / decided:.3f}" if decided else "",
                        "failure_rate": f"{m['rejected'] / decided:.3f}" if decided else "",
                        "est_tokens_total": str(m["est_tokens"]),
                        "avg_latency_ms": f"{sum(latencies) / len(latencies):.1f}" if latencies else "",
                        "latency_samples": str(len(latencies)),
                    },
                ),
            )
            _emit(emitter, urn, SubTypesClass(typeNames=["Agent"]))
            _emit(emitter, urn, ownership)

        for org_name, m in orgs.items():
            urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},observability-{org_name},PROD)"
            urns.append(urn)
            total_verdicts = sum(m["determinism"].values())
            _emit(
                emitter,
                urn,
                DatasetPropertiesClass(
                    name=f"observability: {org_name} org",
                    description=(
                        f"Org-level validation outcomes and gate-determinism distribution for "
                        f"{org_name!r}, from {m['runs']} real persisted runs."
                    ),
                    customProperties={
                        "runs": str(m["runs"]),
                        "runs_accepted": str(m["runs_accepted"]),
                        "gates_passed": str(m["gates_passed"]),
                        "gates_failed": str(m["gates_failed"]),
                        "verdicts_hard": str(m["determinism"]["hard"]),
                        "verdicts_soft": str(m["determinism"]["soft"]),
                        "verdicts_human": str(m["determinism"]["human"]),
                        "hard_verdict_share": (
                            f"{m['determinism']['hard'] / total_verdicts:.3f}" if total_verdicts else ""
                        ),
                    },
                ),
            )
            _emit(emitter, urn, SubTypesClass(typeNames=["Observability"]))
            _emit(emitter, urn, ownership)

        for tenant, total, accepted in ledger:
            urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},usage-{tenant},PROD)"
            urns.append(urn)
            _emit(
                emitter,
                urn,
                DatasetPropertiesClass(
                    name=f"usage ledger: {tenant}",
                    description="Wedge usage ledger — the real record quota and billing decisions are made from.",
                    customProperties={
                        "total_runs": str(total),
                        "accepted_runs": str(accepted or 0),
                    },
                ),
            )
            _emit(emitter, urn, SubTypesClass(typeNames=["UsageLedger"]))
            _emit(emitter, urn, ownership)
        return urns
    finally:
        emitter.close()


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parent.parent
    # The wedge usage ledger belongs to the front door (entropy-os) after the
    # split; ENTROPY_USAGE_DB points there when it relocates. Its default is
    # the historical in-repo location, and read_usage_ledger() already treats
    # a missing file as "no ledger" rather than an error.
    usage_db = Path(os.environ.get("ENTROPY_USAGE_DB", str(root / "hub_data" / "usage.db")))
    urns = emit_observability(root / "hub_data" / "runs", usage_db)
    print(f"emitted {len(urns)} observability entities", file=sys.stderr)
