"""The collector — Entropy's own DataHub, fed by admission.

Fixture SQLite files are built directly (not via the `hunter_engine`/
`opportunity-agency-ai` packages, which aren't dependencies of this repo) —
matching the real on-disk schemas those repos actually write, so readers.py
is exercised against the real shape, not a hand-rolled stand-in.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from collector.collect import collect_one, run_collection
from collector.gate import check_structural
from collector.readers import read_hunter_engine, read_opportunity_hub
from collector.records import AdmissionState, EntropyRecord, record_id
from collector.sources import SourceConfig
from collector.store import CollectorStore


def _hunter_engine_source(tmp_path: Path, name: str = "crypto_hunter", **kw: object) -> SourceConfig:
    repo = tmp_path / name
    (repo / "data").mkdir(parents=True, exist_ok=True)
    kwargs = {"name": name, "title": name, "repo": str(repo), "kind": "hunter_engine", "color": "fff"}
    kwargs.update(kw)
    return SourceConfig(**kwargs)  # type: ignore[arg-type]


def _write_hunter_engine_db(repo: Path, rows: list[tuple[str, dict[str, object]]]) -> None:
    db_path = repo / "data" / "datahub.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE opportunities (id TEXT PRIMARY KEY, name TEXT, type TEXT,"
        " trust_status TEXT, lifecycle TEXT, spec_json TEXT)"
    )
    for opp_id, spec in rows:
        conn.execute(
            "INSERT INTO opportunities (id, name, type, trust_status, lifecycle, spec_json)"
            " VALUES (?, ?, ?, 'verified', 'gated', ?)",
            (opp_id, spec.get("name", opp_id), spec.get("type", "generic"), json.dumps(spec)),
        )
    conn.commit()
    conn.close()


def _verified_spec(**overrides: object) -> dict[str, object]:
    spec: dict[str, object] = {
        "name": "Some Opportunity",
        "type": "airdrop",
        "cost_usd_est": 5.0,
        "verification": [{"check": "domain_age", "passed": True, "data": {}}],
        "outcome": {"payout_usd_est": None},
    }
    spec.update(overrides)
    return spec


# --- readers -----------------------------------------------------------------------------------

def test_read_hunter_engine_reads_only_verified_records(tmp_path: Path) -> None:
    cfg = _hunter_engine_source(tmp_path)
    _write_hunter_engine_db(Path(cfg.repo), [("opp1", _verified_spec(name="Airdrop A"))])
    out = read_hunter_engine(cfg)
    assert len(out) == 1
    assert out[0].source_ref == "opp1"
    assert out[0].payload_ref["name"] == "Airdrop A"
    assert out[0].verification == [{"check": "domain_age", "passed": True, "data": {}}]


def test_read_hunter_engine_missing_db_returns_empty(tmp_path: Path) -> None:
    cfg = _hunter_engine_source(tmp_path)
    assert read_hunter_engine(cfg) == []


def test_read_hunter_engine_skips_a_malformed_row_without_crashing(tmp_path: Path) -> None:
    cfg = _hunter_engine_source(tmp_path)
    db_path = Path(cfg.repo) / "data" / "datahub.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE opportunities (id TEXT PRIMARY KEY, name TEXT, type TEXT,"
        " trust_status TEXT, lifecycle TEXT, spec_json TEXT)"
    )
    conn.execute(
        "INSERT INTO opportunities VALUES ('bad', 'bad', 'x', 'verified', 'gated', 'not json')"
    )
    conn.execute(
        "INSERT INTO opportunities VALUES ('good', 'ok', 'x', 'verified', 'gated', ?)",
        (json.dumps(_verified_spec(name="ok")),),
    )
    conn.commit()
    conn.close()
    out = read_hunter_engine(cfg)
    assert [r.source_ref for r in out] == ["good"]


def test_read_opportunity_hub_explodes_allocation_items(tmp_path: Path) -> None:
    cfg = _hunter_engine_source(tmp_path, name="opportunity_agency", kind="opportunity_hub")
    db_path = Path(cfg.repo) / "data" / "datahub.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE allocations (date TEXT PRIMARY KEY, record_json TEXT, created_at TEXT)")
    record = {
        "date": "2026-07-27",
        "items": [
            {"engine": "crypto_hunter", "opportunity_id": "opp1", "name": "Airdrop A",
             "cost_usd_est": 0.0, "time_minutes_est": 10},
        ],
        "skipped": [],
    }
    conn.execute(
        "INSERT INTO allocations VALUES ('2026-07-27', ?, '2026-07-27T00:00:00Z')",
        (json.dumps(record),),
    )
    conn.commit()
    conn.close()
    out = read_opportunity_hub(cfg)
    assert len(out) == 1
    assert out[0].source_ref == "2026-07-27:crypto_hunter:opp1"
    assert out[0].verification[0]["passed"] is True


# --- structural gate -----------------------------------------------------------------------------

def _record(**overrides: object) -> EntropyRecord:
    fields: dict[str, object] = {
        "id": "abc123",
        "source": "crypto_hunter",
        "source_ref": "opp1",
        "kind": "hunter_engine",
        "collected_at": datetime.now(timezone.utc),
        "verification": [{"check": "domain_age", "passed": True}],
    }
    fields.update(overrides)
    return EntropyRecord(**fields)  # type: ignore[arg-type]


def test_structural_gate_passes_well_formed_verification() -> None:
    assert check_structural(_record()).passed is True


def test_structural_gate_fails_on_empty_verification() -> None:
    verdict = check_structural(_record(verification=[]))
    assert verdict.passed is False
    assert "no verification" in verdict.reason


def test_structural_gate_fails_on_empty_source_ref() -> None:
    assert check_structural(_record(source_ref="  ")).passed is False


def test_structural_gate_fails_on_malformed_verification_entry() -> None:
    verdict = check_structural(_record(verification=[{"check": "x"}]))  # missing "passed"
    assert verdict.passed is False


def test_structural_gate_passes_even_when_the_source_itself_rejected() -> None:
    """A record whose own verification says passed=False is still a
    structurally sound, honestly-collected record — this gate isn't
    re-judging the domain claim."""
    verdict = check_structural(_record(verification=[{"check": "domain_age", "passed": False}]))
    assert verdict.passed is True


# --- store ---------------------------------------------------------------------------------------

def test_upsert_then_get_round_trips(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    rec = _record()
    store.upsert(rec)
    fetched = store.get(rec.id)
    assert fetched is not None
    assert fetched.source_ref == "opp1"
    assert fetched.state == AdmissionState.PENDING


def test_approve_transitions_pending_to_admitted(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    rec = _record()
    store.upsert(rec)
    approved = store.approve(rec.id, "u_alice")
    assert approved is not None
    assert approved.admitted is True
    assert approved.admitted_by == "u_alice"
    assert approved.state == AdmissionState.ADMITTED
    assert store.count_pending() == 0


def test_decline_transitions_pending_to_declined_not_pending(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    rec = _record()
    store.upsert(rec)
    declined = store.decline(rec.id, "u_alice")
    assert declined is not None
    assert declined.admitted is False
    assert declined.state == AdmissionState.DECLINED
    assert store.count_pending() == 0


def test_approve_is_idempotent_on_an_already_decided_record(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    rec = _record()
    store.upsert(rec)
    store.approve(rec.id, "u_alice")
    assert store.approve(rec.id, "u_bob") is None  # already decided — no-op, not an error


def test_approve_unknown_id_returns_none(tmp_path: Path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    assert store.approve("nonexistent", "u_alice") is None


def test_upsert_never_reverts_an_admitted_record_back_to_pending(tmp_path: Path) -> None:
    """The core sticky-decision guarantee: re-running collection on a record
    a human already admitted must not silently undo that decision."""
    store = CollectorStore(tmp_path / "collector.sqlite3")
    rec = _record()
    store.upsert(rec)
    store.approve(rec.id, "u_alice")

    # Simulate a re-collection of the same source record.
    store.upsert(_record())

    fetched = store.get(rec.id)
    assert fetched is not None
    assert fetched.state == AdmissionState.ADMITTED
    assert fetched.admitted_by == "u_alice"


# --- collect orchestrator -------------------------------------------------------------------------

def test_collect_one_auto_admits_when_source_trusts_and_gate_passes(tmp_path: Path) -> None:
    cfg = _hunter_engine_source(tmp_path, default_trust="auto")
    _write_hunter_engine_db(Path(cfg.repo), [("opp1", _verified_spec())])
    store = CollectorStore(tmp_path / "collector.sqlite3")
    count = collect_one(cfg, store)
    assert count == 1
    rec = store.get(record_id(cfg.name, "opp1"))
    assert rec is not None
    assert rec.state == AdmissionState.ADMITTED
    assert rec.admitted_by == "auto:structural-check"


def test_collect_one_holds_when_source_default_trust_is_held(tmp_path: Path) -> None:
    cfg = _hunter_engine_source(tmp_path, default_trust="held")
    _write_hunter_engine_db(Path(cfg.repo), [("opp1", _verified_spec())])
    store = CollectorStore(tmp_path / "collector.sqlite3")
    collect_one(cfg, store)
    rec = store.get(record_id(cfg.name, "opp1"))
    assert rec is not None
    assert rec.state == AdmissionState.PENDING


def test_run_collection_isolates_an_unknown_kind_from_other_sources(tmp_path: Path) -> None:
    good = _hunter_engine_source(tmp_path, name="good_engine", default_trust="held")
    _write_hunter_engine_db(Path(good.repo), [("opp1", _verified_spec())])
    broken = _hunter_engine_source(tmp_path, name="broken_engine", kind="nonexistent_kind")
    store = CollectorStore(tmp_path / "collector.sqlite3")

    counts = run_collection({"good_engine": good, "broken_engine": broken}, store)

    assert counts == {"good_engine": 1, "broken_engine": 0}
    assert len(store.list_by_source("good_engine")) == 1


