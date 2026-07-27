"""ExpiringRegistry — the bounded, self-evicting dict replacement for hub/app.py's
token-keyed session/progress registries. Added alongside the production-quality
audit to fix the unbounded-memory-growth finding.
"""

from __future__ import annotations

from unittest.mock import patch

from hub.expiring_store import ExpiringRegistry


def test_set_then_get_round_trips() -> None:
    registry: ExpiringRegistry[dict] = ExpiringRegistry()
    registry["token-1"] = {"done": False}

    assert registry["token-1"] == {"done": False}
    assert registry.get("token-1") == {"done": False}


def test_get_returns_default_for_an_unknown_key() -> None:
    registry: ExpiringRegistry[dict] = ExpiringRegistry()

    assert registry.get("nope") is None
    assert registry.get("nope", "fallback") == "fallback"


def test_contains_reflects_presence() -> None:
    registry: ExpiringRegistry[dict] = ExpiringRegistry()
    registry["token-1"] = {"done": False}

    assert "token-1" in registry
    assert "token-2" not in registry


def test_in_place_mutation_of_the_stored_value_is_visible_on_next_read() -> None:
    """The real call sites do `registry[token]["events"].append(...)` — the value
    returned by __getitem__ must be the SAME object stored, not a copy."""
    registry: ExpiringRegistry[dict] = ExpiringRegistry()
    registry["token-1"] = {"events": []}

    registry["token-1"]["events"].append("first")
    registry["token-1"]["events"].append("second")

    assert registry["token-1"]["events"] == ["first", "second"]


def test_sweep_now_evicts_entries_older_than_max_age() -> None:
    registry: ExpiringRegistry[dict] = ExpiringRegistry(max_age_seconds=100)
    registry["old"] = {"v": 1}

    with patch("time.monotonic", return_value=1_000_000.0):
        evicted = registry.sweep_now()

    assert evicted == 1
    assert "old" not in registry


def test_sweep_now_keeps_entries_within_max_age() -> None:
    registry: ExpiringRegistry[dict] = ExpiringRegistry(max_age_seconds=100)
    registry["fresh"] = {"v": 1}

    evicted = registry.sweep_now()

    assert evicted == 0
    assert "fresh" in registry


def test_writes_trigger_an_automatic_sweep_every_n_writes() -> None:
    registry: ExpiringRegistry[dict] = ExpiringRegistry(max_age_seconds=100, sweep_every=3)
    registry["old"] = {"v": 1}  # write #1 of 3 toward the next automatic sweep

    # Advance the clock past max_age, then make (sweep_every - 1) more writes —
    # the sweep should not have run yet (write #1 already happened above).
    with patch("time.monotonic", return_value=1_000_000.0):
        registry["new-1"] = {"v": 2}  # write #2
        assert "old" in registry  # not yet swept — only 2 of 3 writes have happened

        registry["new-2"] = {"v": 3}  # write #3 triggers the sweep
        assert "old" not in registry
        assert "new-2" in registry  # the fresh entry survives its own sweep


def test_touch_refreshes_a_keys_age() -> None:
    registry: ExpiringRegistry[dict] = ExpiringRegistry(max_age_seconds=100)
    registry["token-1"] = {"v": 1}

    with patch("time.monotonic", return_value=1_000_000.0):
        registry.touch("token-1")
        evicted = registry.sweep_now()

    assert evicted == 0
    assert "token-1" in registry


def test_touch_on_an_unknown_key_is_a_safe_no_op() -> None:
    registry: ExpiringRegistry[dict] = ExpiringRegistry()

    registry.touch("never-set")  # must not raise

    assert "never-set" not in registry
