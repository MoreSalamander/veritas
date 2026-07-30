"""orgs/hunter_engine_bridge.py — the bridge shared by every Hunter engine
registered as an external Veritas org.

This used to be copy-pasted per org (crypto_hunter had its own bridge.py);
these tests exist to prove the generalization didn't lose anything AND that
the three registry wrappers actually point at three distinct repos — the
exact class of bug a copy-paste-to-generalize refactor risks introducing.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine.memory import MemoryStore
from orgs.hunter_engine_bridge import _outcomes_from_datahub, run_hunter_engine
from orgs.registry import (
    _run_collectible_hunter_bridge,
    _run_crypto_hunter_bridge,
    _run_free_money_hunter_bridge,
)


def _write_datahub(db_path: Path, rows: list[tuple[str, dict[str, object]]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE opportunities (id TEXT PRIMARY KEY, trust_status TEXT,"
        " updated_at TEXT, spec_json TEXT)"
    )
    for i, (status, spec) in enumerate(rows):
        spec = {**spec, "trust_status": status}  # the real schema carries it in both places
        conn.execute(
            "INSERT INTO opportunities VALUES (?, ?, ?, ?)",
            (f"opp{i}", status, f"2026-07-27T0{i}:00:00Z", json.dumps(spec)),
        )
    conn.commit()
    conn.close()


def _spec(**overrides: object) -> dict[str, object]:
    spec: dict[str, object] = {
        "name": "Some Opportunity",
        "discovered_by": "test-scout",
        "verification": [{"check": "domain_age", "passed": True, "data": {}}],
    }
    spec.update(overrides)
    return spec


def test_outcomes_from_datahub_translates_verified_and_rejected_records(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "datahub.sqlite3"
    _write_datahub(db_path, [
        ("verified", _spec(name="Good One")),
        ("rejected", _spec(name="Bad One", verification=[{"check": "domain_age", "passed": False, "data": {}}])),
    ])
    memory = MemoryStore(tmp_path / "memory")

    outcomes = _outcomes_from_datahub(db_path, "crypto-hunter", memory)

    assert len(outcomes) == 2
    accepted_flags = {o.accepted for o in outcomes}
    assert accepted_flags == {True, False}
    for outcome in outcomes:
        assert all(gr.determinism.value == "hard" for gr in outcome.gate_results)


def test_outcomes_from_datahub_missing_db_returns_empty(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory")
    assert _outcomes_from_datahub(tmp_path / "never" / "datahub.sqlite3", "crypto-hunter", memory) == []


def test_run_hunter_engine_reports_the_right_org_name_and_actor(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory")
    fake_proc = MagicMock(returncode=0, stdout="== sweeping ==\n", stderr="")
    with patch("orgs.hunter_engine_bridge.subprocess.run", return_value=fake_proc) as mock_run:
        result = run_hunter_engine("free_money_hunter", tmp_path, MagicMock(), memory, "run today's hunt")

    assert result.org == "free_money_hunter"
    assert result.activity[0].actor == "free-money-hunter"
    # cwd passed to the subprocess must be exactly the repo dir handed in — a
    # copy-paste mistake here would silently run the wrong engine's CLI.
    assert mock_run.call_args.kwargs["cwd"] == tmp_path


def test_run_hunter_engine_reports_failure_without_crashing(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory")
    fake_proc = MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("orgs.hunter_engine_bridge.subprocess.run", return_value=fake_proc):
        result = run_hunter_engine("crypto_hunter", tmp_path, MagicMock(), memory, "run today's hunt")

    assert result.accepted is False
    assert result.outcomes == []
    assert "FAILED" in result.activity[-1].message


def test_all_three_registry_bridges_point_at_distinct_repos(tmp_path: Path) -> None:
    """The exact bug a copy-paste generalization risks: all three orgs
    silently running the same repo's CLI."""
    memory = MemoryStore(tmp_path / "memory")
    fake_proc = MagicMock(returncode=0, stdout="", stderr="")
    cwds = []
    # Bypass the pause pre-flight (orgs/hunter_engine_bridge.py's _is_paused) —
    # this test only cares about which repo dir each bridge targets, and one
    # of the real repos may legitimately have data/pause.json set on disk.
    with patch("orgs.hunter_engine_bridge._is_paused", return_value=False), \
         patch("orgs.hunter_engine_bridge.subprocess.run", return_value=fake_proc) as mock_run:
        for bridge_fn in (_run_crypto_hunter_bridge, _run_collectible_hunter_bridge, _run_free_money_hunter_bridge):
            bridge_fn("goal", MagicMock(), memory)
            cwds.append(mock_run.call_args.kwargs["cwd"])

    assert len(set(cwds)) == 3
    assert {p.name for p in cwds} == {"crypto-hunter", "collectible-hunter", "free-money-hunter"}
