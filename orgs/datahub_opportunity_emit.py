"""Stage 5 (Opportunity Intelligence) emitter: publishes a Hunter engine's
REAL opportunities — read directly from its own datahub.sqlite3, the same
read-only pattern as orgs/hunter_engine_bridge.py — as fully-structured
DataHub entities.

This is also the real-domain half of the toy/real-domain pair:
orgs/datahub_emit.py's build_toy_org_run() fabricates demo data; this
module reads what a real engine's scouts actually discovered and its real
scaffold gate actually verified. Nothing here is invented — every attribute
below maps 1:1 onto a field the Hunter spec already carries:

    source          -> spec.sources[] (urls) + discovered_by
    category        -> spec.type (airdrop/...) + ecosystem
    difficulty      -> spec.eligibility_requirements (count + text)
    estimated time  -> spec.time_minutes_est
    cost            -> spec.cost_usd_est
    potential value -> spec.scores.reward_potential
    risk assessment -> spec.scores.risk
    verification    -> spec.verification[] (the gate's per-check evidence)
    expiration      -> spec.deadline
    completion      -> spec.lifecycle + spec.outcome (acted_at/paid)
    user feedback   -> spec.outcome.notes

QUERYABILITY — DataHub search filters on tags/subtypes, not on arbitrary
customProperties, so the vision's example queries are made real by DERIVED
TAGS computed at emit time. The thresholds are deliberate, stated policy
(documented on the tag itself), not hidden heuristics:

    OppVerified   trust_status == "verified" (the engine's own hard gate)
    OppZeroCost   cost_usd_est == 0 exactly; a null estimate is UNKNOWN
                  cost and honestly gets no tag
    OppUnder30Min time_minutes_est is known and <= 30
    OppHighValue  scores.reward_potential >= 30 (of the engine's 0-40 scale)

Category search works via subTypes: every opportunity is
["Opportunity", <spec.type>], so DataHub's own subtype facet becomes the
category filter.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SubTypesClass,
    TagAssociationClass,
    TagPropertiesClass,
)

GMS_SERVER = "http://localhost:8080"
PLATFORM = "veritas"

_HIGH_VALUE_THRESHOLD = 30  # of the engine's 0-40 reward_potential scale — stated policy
_UNDER_MINUTES = 30

_TAGS = {
    "OppVerified": "trust_status == 'verified' — the Hunter engine's own scaffold gate passed every check.",
    "OppZeroCost": "cost_usd_est == 0 exactly. A null estimate is UNKNOWN cost and does not earn this tag.",
    "OppUnder30Min": f"time_minutes_est known and <= {_UNDER_MINUTES}.",
    "OppHighValue": f"scores.reward_potential >= {_HIGH_VALUE_THRESHOLD} on the engine's 0-40 scale — stated policy, not a hidden heuristic.",
}


def _emit(emitter: DatahubRestEmitter, urn: str, aspect) -> None:
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def _ensure_tags(emitter: DatahubRestEmitter) -> None:
    for name, description in _TAGS.items():
        _emit(emitter, f"urn:li:tag:{name}", TagPropertiesClass(name=name, description=description))


def _derived_tags(spec: dict) -> list[str]:
    tags: list[str] = []
    if spec.get("trust_status") == "verified":
        tags.append("OppVerified")
    if spec.get("cost_usd_est") == 0:
        tags.append("OppZeroCost")
    time_est = spec.get("time_minutes_est")
    if time_est is not None and time_est <= _UNDER_MINUTES:
        tags.append("OppUnder30Min")
    reward = (spec.get("scores") or {}).get("reward_potential")
    if reward is not None and reward >= _HIGH_VALUE_THRESHOLD:
        tags.append("OppHighValue")
    return tags


def _opportunity_properties(spec: dict) -> DatasetPropertiesClass:
    scores = spec.get("scores") or {}
    outcome = spec.get("outcome") or {}
    requirements = spec.get("eligibility_requirements") or []
    sources = spec.get("sources") or []
    return DatasetPropertiesClass(
        name=spec.get("name") or spec.get("id", "unnamed"),
        description=spec.get("summary") or "",
        customProperties={
            "opportunity_id": spec.get("id") or "",
            "category": spec.get("type") or "",
            "ecosystem": spec.get("ecosystem") or "",
            "sources": ",".join(s.get("url", "") for s in sources),
            "discovered_by": spec.get("discovered_by") or "",
            "discovered_at": spec.get("discovered_at") or "",
            "difficulty_requirements_count": str(len(requirements)),
            "difficulty_requirements": " | ".join(requirements)[:500],
            "estimated_time_minutes": str(spec["time_minutes_est"]) if spec.get("time_minutes_est") is not None else "",
            "cost_usd_est": str(spec["cost_usd_est"]) if spec.get("cost_usd_est") is not None else "",
            "potential_value_score": str(scores["reward_potential"]) if scores.get("reward_potential") is not None else "",
            "risk_score": str(scores["risk"]) if scores.get("risk") is not None else "",
            "risk_narrative": (scores.get("narrative") or "")[:500],
            "expiration_deadline": spec.get("deadline") or "",
            "completion_status": spec.get("lifecycle") or "",
            "completion_acted_at": outcome.get("acted_at") or "",
            "completion_paid": str(outcome["paid"]) if outcome.get("paid") is not None else "",
            "user_feedback": outcome.get("notes") or "",
            "trust_status": spec.get("trust_status") or "",
            "gate_version": spec.get("gate_version") or "",
            "verification_history": json.dumps(
                [{"check": v.get("check"), "passed": v.get("passed")} for v in spec.get("verification") or []]
            ),
        },
    )


def emit_hunter_opportunities(
    org_name: str,
    repo_dir: Path,
    gms_server: str = GMS_SERVER,
) -> list[str]:
    """Read one Hunter engine's real opportunities (read-only, same contract
    as hunter_engine_bridge) and publish each as a structured DataHub
    entity. Returns the emitted URNs."""
    db_path = repo_dir / "data" / "datahub.sqlite3"
    if not db_path.exists():
        raise FileNotFoundError(f"no Hunter store at {db_path}")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT spec_json FROM opportunities ORDER BY discovered_at").fetchall()
    finally:
        conn.close()

    actor = org_name.replace("_", "-")
    owner = OwnershipClass(
        owners=[OwnerClass(owner=f"urn:li:corpGroup:veritas-{actor}", type=OwnershipTypeClass.DATAOWNER)]
    )
    emitter = DatahubRestEmitter(gms_server=gms_server)
    urns: list[str] = []
    try:
        _ensure_tags(emitter)
        for (spec_json,) in rows:
            spec = json.loads(spec_json)
            opp_id = spec.get("id") or "unknown"
            urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{actor}-{opp_id},PROD)"
            urns.append(urn)
            _emit(emitter, urn, _opportunity_properties(spec))
            _emit(emitter, urn, SubTypesClass(typeNames=["Opportunity", spec.get("type") or "unknown"]))
            _emit(emitter, urn, owner)
            tags = _derived_tags(spec)
            if tags:
                _emit(
                    emitter,
                    urn,
                    GlobalTagsClass(tags=[TagAssociationClass(tag=f"urn:li:tag:{t}") for t in tags]),
                )
        return urns
    finally:
        emitter.close()


if __name__ == "__main__":
    import sys

    urns = emit_hunter_opportunities("crypto_hunter", Path.home() / "MoreSalamander" / "crypto-hunter")
    print(f"emitted {len(urns)} real crypto-hunter opportunities", file=sys.stderr)
