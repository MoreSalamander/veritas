"""orgs/datahub_workflow_emit.py — offline, deterministic.

phase_spans() is the pure heart of the Stage 8 emitter: collapsing a
run's real activity log into ordered per-phase spans, honestly labeling
derived vs recorded timestamps. The live emission itself is exercised
against a running DataHub, same convention as the other emitters.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "datahub",
    reason="acryl-datahub needs Python 3.12 here (pydantic-core has no 3.14 wheel yet) — "
    "run this file with .venv-datahub, not the repo's main .venv",
)

from orgs.datahub_workflow_emit import phase_spans


def _run(activity: list[dict]) -> dict:
    return {"id": "run_x", "created_at": "2026-01-01T00:00:00+00:00", "activity": activity}


def test_phase_spans_groups_consecutive_same_phase_entries():
    spans = phase_spans(
        _run(
            [
                {"phase": "verify", "duration_ms": 10.0, "at": None},
                {"phase": "verify", "duration_ms": 5.0, "at": None},
                {"phase": "persist", "duration_ms": 2.0, "at": None},
            ]
        )
    )
    assert [s["phase"] for s in spans] == ["verify", "persist"]
    assert spans[0]["duration_ms"] == 15.0


def test_phase_spans_derives_start_times_from_cumulative_durations():
    spans = phase_spans(
        _run(
            [
                {"phase": "verify", "duration_ms": 100.0, "at": None},
                {"phase": "persist", "duration_ms": 50.0, "at": None},
            ]
        )
    )
    assert spans[0]["derived"] is True
    # persist starts after verify's measured 100ms
    assert spans[1]["start_ms"] == spans[0]["start_ms"] + 100


def test_phase_spans_recorded_timestamp_is_used_exactly():
    from orgs.datahub_workflow_emit import _millis

    at = "2026-01-01T00:00:30+00:00"
    spans = phase_spans(_run([{"phase": "verify", "duration_ms": 1.0, "at": at}]))
    assert spans[0]["derived"] is False
    assert spans[0]["start_ms"] == _millis(at)
