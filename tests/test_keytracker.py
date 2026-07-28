"""hub/keytracker.py — the API key inventory. No test here ever asserts
anything about a secret VALUE, because KeyRecord has no field capable of
holding one; these tests are entirely about the metadata contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hub.keytracker import KeyRecord, KeyTrackerStore


def _store(tmp_path: Path) -> KeyTrackerStore:
    return KeyTrackerStore(tmp_path / "keytracker.sqlite3")


def test_upsert_then_get_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = KeyRecord(
        id="anthropic-primary", label="Anthropic (primary)", provider="anthropic",
        keychain_account="entropy-keytracker:anthropic-primary", env_var_name="ANTHROPIC_API_KEY",
        used_by_repos=["crypto-hunter", "collectible-hunter"],
    )
    store.upsert(record)
    fetched = store.get("anthropic-primary")
    assert fetched is not None
    assert fetched.provider == "anthropic"
    assert fetched.used_by_repos == ["crypto-hunter", "collectible-hunter"]
    assert fetched.status == "active"


def test_get_unknown_id_returns_none(tmp_path: Path) -> None:
    assert _store(tmp_path).get("nonexistent") is None


def test_list_all_returns_every_tracked_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(KeyRecord(
        id="a", label="A", provider="anthropic",
        keychain_account="x", env_var_name="ANTHROPIC_API_KEY",
    ))
    store.upsert(KeyRecord(
        id="b", label="B", provider="openai",
        keychain_account="y", env_var_name="OPENAI_API_KEY",
    ))
    assert {r.id for r in store.list_all()} == {"a", "b"}


def test_mark_rotated_updates_last_rotated_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(KeyRecord(
        id="a", label="A", provider="anthropic",
        keychain_account="x", env_var_name="ANTHROPIC_API_KEY",
    ))
    before = store.get("a")
    assert before is not None and before.last_rotated_at is None

    rotated = store.mark_rotated("a")
    assert rotated is not None
    assert rotated.last_rotated_at is not None
    assert (datetime.now(timezone.utc) - rotated.last_rotated_at) < timedelta(seconds=5)


def test_revoke_sets_status_but_keeps_the_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(KeyRecord(
        id="a", label="A", provider="anthropic",
        keychain_account="x", env_var_name="ANTHROPIC_API_KEY",
    ))
    revoked = store.revoke("a")
    assert revoked is not None
    assert revoked.status == "revoked"
    # Still fetchable — a compromised key's history stays auditable, not deleted.
    assert store.get("a") is not None


def test_upsert_is_idempotent_and_updates_in_place(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(KeyRecord(
        id="a", label="First label", provider="anthropic",
        keychain_account="x", env_var_name="ANTHROPIC_API_KEY",
    ))
    store.upsert(KeyRecord(
        id="a", label="Updated label", provider="anthropic",
        keychain_account="x", env_var_name="ANTHROPIC_API_KEY",
        used_by_repos=["opportunity-agency-ai"],
    ))
    fetched = store.get("a")
    assert fetched is not None
    assert fetched.label == "Updated label"
    assert fetched.used_by_repos == ["opportunity-agency-ai"]
    assert len(store.list_all()) == 1


# --- /api/keytracker/keys — never returns a value, ever -----------------------------------------

@pytest.fixture
def client(tmp_path: Path):
    from fastapi.testclient import TestClient

    import hub.app as app_mod

    app = app_mod.create_app(data_dir=tmp_path / "hub_data")
    return TestClient(app)


def test_keytracker_keys_endpoint_lists_metadata_with_no_repos_and_degrades_spend(client) -> None:
    """No repo directories exist under this tmp_path, so spend must degrade
    to 'unattributed' (None) rather than raise — same posture as the
    collector's schema-mismatch handling."""
    import hub.app as app_mod

    app_mod  # keep the import referenced; the fixture already built the app
    resp = client.get("/api/keytracker/keys")
    assert resp.status_code == 200
    assert resp.json() == []  # nothing tracked yet in a fresh store


def test_keytracker_keys_endpoint_never_serializes_a_value_field(tmp_path: Path) -> None:
    """Structural guarantee: even inspecting the raw JSON keys returned, none
    of them could ever be a secret value field — KeyRecord has none."""
    from fastapi.testclient import TestClient

    import hub.app as app_mod

    store = KeyTrackerStore(tmp_path / "hub_data" / "keytracker.sqlite3")
    store.upsert(KeyRecord(
        id="anthropic-primary", label="Anthropic (primary)", provider="anthropic",
        keychain_account="entropy-keytracker:anthropic-primary", env_var_name="ANTHROPIC_API_KEY",
        # A repo name guaranteed not to exist on disk, so this test stays
        # deterministic regardless of what's actually installed under
        # ~/MoreSalamander on the machine running it.
        used_by_repos=["nonexistent-repo-for-test-only"],
    ))
    app = app_mod.create_app(data_dir=tmp_path / "hub_data")
    client = TestClient(app)
    resp = client.get("/api/keytracker/keys")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert set(body[0]) == {
        "id", "label", "provider", "env_var_name", "used_by_repos",
        "status", "days_since_rotation", "spend_usd",
    }
    assert body[0]["spend_usd"] is None  # no such repo on disk -> unattributed, not a crash
