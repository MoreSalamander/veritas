"""RunStore — the persistence layer behind the dashboard's run history.

Focus: the corruption-resilience behavior added alongside the production-quality
audit (a single bad run file must never take down `get` or `list`), plus the
ordinary save/get/list round trip it builds on.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from hub.store import RunStore, RunSummary


def _summary(run_id: str, created_at: str = "2026-01-01T00:00:00+00:00") -> RunSummary:
    return RunSummary(
        id=run_id,
        org="software",
        model="local",
        goal="a function that adds two numbers",
        accepted=True,
        created_at=created_at,
        informed_by=[],
        artifacts=[],
        gates=[],
        activity=[],
    )


def test_save_then_get_round_trips(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.save(_summary("run-1"))

    loaded = store.get("run-1")

    assert loaded is not None
    assert loaded["id"] == "run-1"
    assert loaded["accepted"] is True


def test_get_returns_none_for_a_run_id_that_was_never_saved(tmp_path: Path) -> None:
    store = RunStore(tmp_path)

    assert store.get("never-saved") is None


def test_get_treats_a_corrupt_run_file_as_not_found_instead_of_raising(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    (tmp_path / "run-1.json").write_text("{not valid json", encoding="utf-8")

    assert store.get("run-1") is None


def test_list_skips_a_corrupt_file_but_still_returns_the_good_ones(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.save(_summary("run-1", created_at="2026-01-01T00:00:00+00:00"))
    store.save(_summary("run-2", created_at="2026-01-02T00:00:00+00:00"))
    (tmp_path / "run-corrupt.json").write_text("{not valid json", encoding="utf-8")

    runs = store.list()

    assert {r["id"] for r in runs} == {"run-1", "run-2"}


def test_list_orders_most_recent_first(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.save(_summary("older", created_at="2026-01-01T00:00:00+00:00"))
    store.save(_summary("newer", created_at="2026-01-02T00:00:00+00:00"))

    runs = store.list()

    assert [r["id"] for r in runs] == ["newer", "older"]
