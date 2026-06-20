"""Production Studio (structural spine) — consistency through the chain, verified.

The cast proposes concept -> script -> storyboard; the gates enforce referential integrity across
every boundary. Driven offline with a scripted provider: a coherent production ships, and each kind
of inconsistency (an undeclared character, a dropped beat, an orphan shot) is caught by the gate
that owns it. "Done" here means consistent, not good — goodness is the human tier, not tested here.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.production_studio.gates import (
    ConceptScorerGate,
    ScriptGroundingGate,
    StoryboardCoverageGate,
    StoryboardGroundingGate,
)
from orgs.production_studio.pipeline import build_production
from orgs.production_studio.production import (
    concept_completeness,
    parse_concept,
    parse_script,
)

CONCEPT = json.dumps({
    "title": "Why the Sky is Blue", "logline": "a curious kid learns why the sky looks blue",
    "audience": "kids", "tone": "warm", "target_seconds": 30,
    "entities": ["Mia", "the Sun", "the sky", "air molecules"],
})
SCRIPT = json.dumps({"scenes": [
    {"heading": "A sunny afternoon", "beats": [
        {"narration": "Mia looks up at the bright blue sky and wonders why it is blue today.",
         "entities": ["Mia", "the sky"]},
        {"narration": "The Sun pours its light down, and that light is secretly every color at once.",
         "entities": ["the Sun"]}]},
    {"heading": "Inside the light", "beats": [
        {"narration": "Tiny air molecules scatter the blue part of the light all across the sky.",
         "entities": ["air molecules", "the sky"]}]},
]})  # beats parse to ids s1b1, s1b2, s2b1
STORYBOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "wide shot of Mia on the grass looking up", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "the Sun radiating warm beams", "entities": ["the Sun"]},
    {"beat_id": "s2b1", "description": "close-up of air molecules bouncing blue light", "entities": ["air molecules"]},
]})

# inconsistencies, each tripping a different gate
SCRIPT_UNDECLARED = json.dumps({"scenes": [{"heading": "x", "beats": [
    {"narration": "A wise Narrator explains the whole thing to Mia.", "entities": ["Narrator", "Mia"]}]}]})
STORYBOARD_GAP = json.dumps({"shots": [  # s1b2 and s2b1 left uncovered
    {"beat_id": "s1b1", "description": "Mia looks up", "entities": ["Mia"]}]})
STORYBOARD_ORPHAN = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "Mia", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "Sun", "entities": ["the Sun"]},
    {"beat_id": "s2b1", "description": "molecules", "entities": ["air molecules"]},
    {"beat_id": "s9b9", "description": "a dragon nobody scripted", "entities": ["Mia"]}]})


def _art(payload: str) -> Artifact:
    return Artifact.propose(type="t", owner="test", payload=payload, rationale="t")


def _provider(script: str = SCRIPT, storyboard: str = STORYBOARD) -> ScriptedProvider:
    return ScriptedProvider({"concept": CONCEPT, "scriptwriter": script, "storyboard-artist": storyboard})


# --- the chain ----------------------------------------------------------------------------

def test_coherent_production_ships_whole_chain(tmp_path):
    res = build_production("explain why the sky is blue, for kids", _provider(), MemoryStore(tmp_path))
    assert res.accepted
    assert len(res.outcomes) == 3 and all(o.accepted for o in res.outcomes)
    assert [o.artifact.type for o in res.outcomes] == ["concept", "script", "storyboard"]


def test_undeclared_character_stops_at_the_script(tmp_path):
    res = build_production("x", _provider(script=SCRIPT_UNDECLARED), MemoryStore(tmp_path))
    assert not res.accepted
    # concept shipped, script was rejected, storyboard was never even proposed
    assert len(res.outcomes) == 2
    assert res.outcomes[0].accepted and not res.outcomes[1].accepted


def test_dropped_beat_fails_storyboard_coverage(tmp_path):
    res = build_production("x", _provider(storyboard=STORYBOARD_GAP), MemoryStore(tmp_path))
    assert not res.accepted and len(res.outcomes) == 3
    assert res.outcomes[1].accepted and not res.outcomes[2].accepted


# --- the gates, directly ------------------------------------------------------------------

def test_concept_completeness_flags_missing_fields():
    ok, missing = concept_completeness(parse_concept(json.dumps({"title": "T"})))
    assert not ok and "entities" in missing and "target_seconds" in missing


def test_script_grounding_catches_undeclared_entity():
    concept = parse_concept(CONCEPT)
    res = ScriptGroundingGate(concept).check(_art(SCRIPT_UNDECLARED))
    assert not res.passed and "Narrator" in res.evidence


def test_storyboard_coverage_catches_dropped_beat():
    script = parse_script(SCRIPT)
    res = StoryboardCoverageGate(script).check(_art(STORYBOARD_GAP))
    assert not res.passed and "s1b2" in res.evidence and "s2b1" in res.evidence


def test_storyboard_grounding_catches_orphan_shot():
    script = parse_script(SCRIPT)
    res = StoryboardGroundingGate(script).check(_art(STORYBOARD_ORPHAN))
    assert not res.passed and "s9b9" in res.evidence


def test_coherent_storyboard_passes_both_storyboard_gates():
    script = parse_script(SCRIPT)
    assert StoryboardCoverageGate(script).check(_art(STORYBOARD)).passed
    assert StoryboardGroundingGate(script).check(_art(STORYBOARD)).passed
