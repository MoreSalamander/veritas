"""The developer cloud toggle: the override moves the DEFAULT, never a choice."""

import pytest

from engine import catalog


def test_override_rides_the_default_only(monkeypatch):
    seen = {}

    class FakeProvider:
        pass

    # api_key is accepted and ignored: provider_for() now hands the resolved
    # credential to the client it builds, because a running server cannot
    # rewrite its own environment for the next request. This test is about
    # which MODEL the toggle selects, so the key is irrelevant to it — but the
    # stub has to match the real signature or it fails on the argument rather
    # than on the behaviour under test.
    def fake_claude(model_id, api_key=""):
        seen["id"] = model_id
        return FakeProvider()

    monkeypatch.setattr(catalog, "ClaudeProvider", fake_claude)
    try:
        catalog.set_default_override("haiku")
        catalog.provider_for(catalog.DEFAULT_MODEL)
        if catalog.MODELS[catalog.DEFAULT_MODEL]["kind"] == "claude":
            pass  # env default already cloud; the assertion below still holds
        assert seen.get("id") == catalog.MODELS["haiku"]["id"], "default rides the toggle"
        seen.clear()
        catalog.provider_for("opus")
        assert seen.get("id") == catalog.MODELS["opus"]["id"], "an explicit pick always wins"
    finally:
        catalog.set_default_override(None)


def test_override_refuses_unknown_models():
    with pytest.raises(ValueError, match="unknown model"):
        catalog.set_default_override("gpt-11-ultra")
    assert catalog.get_default_override() is None
