"""orgs/datahub_observability_emit.py — offline, deterministic.

compute_agent_metrics is the aggregation the Stage 6 success/failure
rates and gate-determinism distribution depend on entirely — worth
proving against small, hand-built run fixtures rather than trusting it
against real data alone.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip(
    "datahub",
    reason="acryl-datahub needs Python 3.12 here (pydantic-core has no 3.14 wheel yet) — "
    "run this file with .venv-datahub, not the repo's main .venv",
)

from orgs.datahub_observability_emit import compute_agent_metrics, read_usage_ledger


def _write_run(tmp_path, name: str, run: dict) -> None:
    (tmp_path / f"{name}.json").write_text(json.dumps(run))


def test_agent_success_and_failure_counts(tmp_path):
    _write_run(
        tmp_path,
        "run1",
        {
            "org": "software",
            "artifacts": [
                {"owner": "dev-agent", "status": "accepted", "payload": "x" * 40},
                {"owner": "dev-agent", "status": "rejected", "payload": "y" * 4},
            ],
            "gates": [],
            "activity": [],
        },
    )
    agents, _ = compute_agent_metrics(tmp_path)
    assert agents["dev-agent"]["proposals"] == 2
    assert agents["dev-agent"]["accepted"] == 1
    assert agents["dev-agent"]["rejected"] == 1
    assert agents["dev-agent"]["est_tokens"] > 0  # real estimate_tokens, not zero


def test_org_gate_determinism_distribution(tmp_path):
    _write_run(
        tmp_path,
        "run1",
        {
            "org": "software",
            "artifacts": [],
            "gates": [
                {"determinism": "hard", "passed": True},
                {"determinism": "hard", "passed": False},
                {"determinism": "soft", "passed": True},
            ],
            "activity": [],
        },
    )
    _, orgs = compute_agent_metrics(tmp_path)
    org = orgs["software"]
    assert org["gates_passed"] == 2
    assert org["gates_failed"] == 1
    assert org["determinism"] == {"hard": 2, "soft": 1, "human": 0}


def test_average_latency_from_real_activity_durations(tmp_path):
    _write_run(
        tmp_path,
        "run1",
        {
            "org": "software",
            "artifacts": [],
            "gates": [],
            "activity": [
                {"actor": "spec-agent", "duration_ms": 10.0},
                {"actor": "spec-agent", "duration_ms": 30.0},
                {"actor": "spec-agent", "duration_ms": 0},  # falsy duration excluded, not averaged as 0
            ],
        },
    )
    agents, _ = compute_agent_metrics(tmp_path)
    assert agents["spec-agent"]["latencies"] == [10.0, 30.0]


def test_read_usage_ledger_returns_empty_when_db_missing(tmp_path):
    assert read_usage_ledger(tmp_path / "does_not_exist.db") == []
