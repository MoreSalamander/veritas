"""orgs/datahub_opportunity_emit.py — offline, deterministic.

_derived_tags is the pure logic the Stage 5 example queries depend on
entirely — if it's wrong, "verified AND under 30 min" silently returns
the wrong set with no error. Worth pinning exactly, including the
null-cost edge case (a null estimate is UNKNOWN cost, not zero).
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "datahub",
    reason="acryl-datahub needs Python 3.12 here (pydantic-core has no 3.14 wheel yet) — "
    "run this file with .venv-datahub, not the repo's main .venv",
)

from orgs.datahub_opportunity_emit import _derived_tags


def test_verified_tag_requires_exact_trust_status():
    assert "OppVerified" in _derived_tags({"trust_status": "verified"})
    assert "OppVerified" not in _derived_tags({"trust_status": "pending"})
    assert "OppVerified" not in _derived_tags({})


def test_zero_cost_tag_requires_exact_zero_not_null():
    assert "OppZeroCost" in _derived_tags({"cost_usd_est": 0})
    assert "OppZeroCost" not in _derived_tags({"cost_usd_est": None})  # unknown, not free
    assert "OppZeroCost" not in _derived_tags({"cost_usd_est": 5})
    assert "OppZeroCost" not in _derived_tags({})


def test_under_30_min_tag_boundary():
    assert "OppUnder30Min" in _derived_tags({"time_minutes_est": 30})
    assert "OppUnder30Min" in _derived_tags({"time_minutes_est": 15})
    assert "OppUnder30Min" not in _derived_tags({"time_minutes_est": 31})
    assert "OppUnder30Min" not in _derived_tags({"time_minutes_est": None})


def test_high_value_tag_boundary():
    assert "OppHighValue" in _derived_tags({"scores": {"reward_potential": 30}})
    assert "OppHighValue" not in _derived_tags({"scores": {"reward_potential": 29}})
    assert "OppHighValue" not in _derived_tags({"scores": {}})
    assert "OppHighValue" not in _derived_tags({})


def test_a_fully_qualifying_opportunity_gets_every_tag():
    spec = {
        "trust_status": "verified",
        "cost_usd_est": 0,
        "time_minutes_est": 10,
        "scores": {"reward_potential": 40},
    }
    assert set(_derived_tags(spec)) == {"OppVerified", "OppZeroCost", "OppUnder30Min", "OppHighValue"}
