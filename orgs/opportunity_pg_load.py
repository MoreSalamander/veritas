"""Loads every Hunter engine's real opportunities into Postgres, normalized
into real columns — the warehouse the DataHub Analytics Agent actually
queries.

This is a separate pipeline from orgs/datahub_opportunity_emit.py on
purpose: that module publishes opportunities as DataHub *entities* (for the
catalog/lineage story); the Analytics Agent doesn't query DataHub's
metadata directly, it queries a real SQL warehouse and uses DataHub only as
a context layer. Both pipelines read the same read-only source (each
engine's own data/datahub.sqlite3, same contract as hunter_engine_bridge)
so they can never disagree about what an opportunity actually is.

Safe to re-run: every load is an upsert keyed on (org, id).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import psycopg

PG_DSN = "dbname=opportunity_agency"

_ORGS: dict[str, str] = {
    "crypto_hunter": "crypto-hunter",
    "collectible_hunter": "collectible-hunter",
    "free_money_hunter": "free-money-hunter",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    org               TEXT NOT NULL,
    id                TEXT NOT NULL,
    name              TEXT,
    opp_type          TEXT,
    ecosystem         TEXT,
    category          TEXT,
    discovered_by     TEXT,
    discovered_at     TIMESTAMPTZ,
    cost_usd_est      NUMERIC,
    time_minutes_est  INTEGER,
    reward_potential  NUMERIC,
    risk_score        NUMERIC,
    risk_narrative    TEXT,
    deadline          TIMESTAMPTZ,
    lifecycle         TEXT,
    trust_status      TEXT,
    outcome_acted_at  TIMESTAMPTZ,
    outcome_paid      BOOLEAN,
    outcome_notes     TEXT,
    raw_spec          JSONB,
    PRIMARY KEY (org, id)
);
COMMENT ON TABLE opportunities IS
  'Real opportunities discovered by Veritas Hunter engines (crypto_hunter, '
  'collectible_hunter, free_money_hunter). trust_status = verified means '
  'the engine''s own deterministic, fail-closed gate accepted it.';
"""

_UPSERT = """
INSERT INTO opportunities (
    org, id, name, opp_type, ecosystem, category, discovered_by, discovered_at,
    cost_usd_est, time_minutes_est, reward_potential, risk_score, risk_narrative,
    deadline, lifecycle, trust_status, outcome_acted_at, outcome_paid,
    outcome_notes, raw_spec
) VALUES (
    %(org)s, %(id)s, %(name)s, %(opp_type)s, %(ecosystem)s, %(category)s,
    %(discovered_by)s, %(discovered_at)s, %(cost_usd_est)s, %(time_minutes_est)s,
    %(reward_potential)s, %(risk_score)s, %(risk_narrative)s, %(deadline)s,
    %(lifecycle)s, %(trust_status)s, %(outcome_acted_at)s, %(outcome_paid)s,
    %(outcome_notes)s, %(raw_spec)s
)
ON CONFLICT (org, id) DO UPDATE SET
    name = EXCLUDED.name, opp_type = EXCLUDED.opp_type,
    ecosystem = EXCLUDED.ecosystem, category = EXCLUDED.category,
    reward_potential = EXCLUDED.reward_potential, risk_score = EXCLUDED.risk_score,
    lifecycle = EXCLUDED.lifecycle, trust_status = EXCLUDED.trust_status,
    outcome_acted_at = EXCLUDED.outcome_acted_at, outcome_paid = EXCLUDED.outcome_paid,
    outcome_notes = EXCLUDED.outcome_notes, raw_spec = EXCLUDED.raw_spec;
"""


def _row_from_spec(org: str, spec: dict[str, Any]) -> dict[str, Any]:
    scores = spec.get("scores") or {}
    outcome = spec.get("outcome") or {}
    return {
        "org": org,
        "id": spec.get("id") or "unknown",
        "name": spec.get("name") or spec.get("id"),
        "opp_type": spec.get("type"),
        "ecosystem": spec.get("ecosystem"),
        "category": spec.get("category"),  # collectible-hunter only; null elsewhere
        "discovered_by": spec.get("discovered_by"),
        "discovered_at": spec.get("discovered_at"),
        "cost_usd_est": spec.get("cost_usd_est"),
        "time_minutes_est": spec.get("time_minutes_est"),
        "reward_potential": scores.get("reward_potential"),
        "risk_score": scores.get("risk"),
        "risk_narrative": scores.get("narrative"),
        "deadline": spec.get("deadline"),
        "lifecycle": spec.get("lifecycle"),
        "trust_status": spec.get("trust_status"),
        "outcome_acted_at": outcome.get("acted_at"),
        "outcome_paid": outcome.get("paid"),
        "outcome_notes": outcome.get("notes"),
        "raw_spec": json.dumps(spec),
    }


def load_engine(conn: psycopg.Connection, org: str, repo_dir: Path) -> int:
    """Read one engine's real opportunities (read-only) and upsert them into
    Postgres. Returns how many rows were loaded; 0 (not an error) if the
    engine has no store yet."""
    db_path = repo_dir / "data" / "datahub.sqlite3"
    if not db_path.exists():
        return 0

    sconn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = sconn.execute("SELECT spec_json FROM opportunities").fetchall()
    finally:
        sconn.close()

    with conn.cursor() as cur:
        for (spec_json,) in rows:
            cur.execute(_UPSERT, _row_from_spec(org, json.loads(spec_json)))
    conn.commit()
    return len(rows)


def load_all(dsn: str = PG_DSN, moresalamander_dir: Path = Path.home() / "MoreSalamander") -> dict[str, int]:
    conn = psycopg.connect(dsn)
    try:
        conn.execute(_SCHEMA)
        conn.commit()
        counts = {}
        for org, repo_name in _ORGS.items():
            counts[org] = load_engine(conn, org, moresalamander_dir / repo_name)
        return counts
    finally:
        conn.close()


if __name__ == "__main__":
    result = load_all()
    for org, n in result.items():
        print(f"{org}: {n} opportunities loaded")
