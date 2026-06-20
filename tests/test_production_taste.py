"""P25f — the taste tier: create mode for a production. The human is the gate for feel.

The whole chain is the machine floor; a human approves the residue. Approve → human-approved record
+ the style profile compounds. Request changes → the production re-runs. A production that can't pass
the machine floor never reaches the human. Driven offline (stub assets, no publisher, scripted cast).
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.production_studio.assets import StubGenerator
from orgs.production_studio.taste import (
    ProductionProfileStore,
    Review,
    build_create_production,
)

CONCEPT = json.dumps({"title": "Why the Sky is Blue", "logline": "a kid learns why the sky is blue",
                      "audience": "kids", "tone": "warm", "target_seconds": 20,
                      "entities": ["Mia", "the sun", "air molecules"]})
SCRIPT = json.dumps({"scenes": [
    {"heading": "A", "beats": [
        {"narration": "Mia looks up at the wide blue sky and wonders why it is blue.", "entities": ["Mia"]},
        {"narration": "The sun pours its light across the whole town below.", "entities": ["the sun"]}]},
    {"heading": "B", "beats": [
        {"narration": "Tiny air molecules scatter the blue light everywhere.", "entities": ["air molecules"]}]},
]})
STORYBOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "Mia on the grass", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "the sun beaming", "entities": ["the sun"]},
    {"beat_id": "s2b1", "description": "molecules scattering", "entities": ["air molecules"]}]})
SCRIPT_BAD = json.dumps({"scenes": [{"heading": "x", "beats": [
    {"narration": "A Narrator explains it all to Mia.", "entities": ["Narrator", "Mia"]}]}]})


def _provider(script: str = SCRIPT) -> ScriptedProvider:
    return ScriptedProvider({"concept": CONCEPT, "scriptwriter": script, "storyboard-artist": STORYBOARD})


def _kwargs(tmp_path):
    return dict(asset_generator=StubGenerator(64, 48), asset_dir=tmp_path / "a")


def test_approve_ships_human_approved_and_teaches_profile(tmp_path):
    store = ProductionProfileStore(tmp_path / "prod.json")
    res = build_create_production("explain why the sky is blue", _provider(), MemoryStore(tmp_path),
                                  review=lambda r: Review(True), profile_store=store, **_kwargs(tmp_path))
    assert res.accepted and res.machine_verified and res.memory_path
    profile = store.load()
    assert profile.approvals == 1 and profile.tone_votes.get("warm") == 1
    assert profile.hint() and "warm" in profile.hint()


def test_request_changes_then_approve_reruns(tmp_path):
    calls = []

    def review(_r):
        calls.append(1)
        return Review(True) if len(calls) >= 2 else Review(False, "make it punchier")

    res = build_create_production("x", _provider(), MemoryStore(tmp_path),
                                  review=review, max_attempts=3, **_kwargs(tmp_path))
    assert res.accepted and res.iterations == 2


def test_machine_floor_failure_never_reaches_the_human(tmp_path):
    asked = []
    res = build_create_production("x", _provider(script=SCRIPT_BAD), MemoryStore(tmp_path),
                                  review=lambda r: (asked.append(1), Review(True))[1], **_kwargs(tmp_path))
    assert not res.accepted and not res.machine_verified
    assert not asked  # the chain was refused before any human judgment


def test_machine_verified_but_never_approved(tmp_path):
    res = build_create_production("x", _provider(), MemoryStore(tmp_path),
                                  review=lambda r: Review(False, "nope"), max_attempts=2,
                                  **_kwargs(tmp_path))
    assert res.machine_verified and not res.accepted and not res.memory_path
