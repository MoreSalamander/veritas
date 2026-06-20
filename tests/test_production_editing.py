"""P25d — editing/assembly, verified by conformance + temporal integrity.

The editor lays the shots out in storyboard order and gives each its beat's narration time (split
when a beat has several shots). The gates prove the cut keeps every shot in order and that the
timeline is contiguous with audio in sync. Driven offline with the stub generator.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from orgs.production_studio.assets import StubGenerator, parse_assets
from orgs.production_studio.editing import (
    Editor,
    EditorAgent,
    SequenceCoverageGate,
    TimelineIntegrityGate,
    parse_timeline,
)
from orgs.production_studio.production import parse_script, parse_storyboard

# beat s1b1 has TWO shots (it must split its narration time); s1b2 has one.
SCRIPT = json.dumps({"scenes": [{"heading": "A", "beats": [
    {"narration": "Mia waves hello to the whole sleepy little town below her.", "entities": ["Mia"]},
    {"narration": "The sun climbs slowly over the rooftops.", "entities": ["the sun"]}]}]})
STORYBOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "Mia waving, wide", "entities": ["Mia"]},
    {"beat_id": "s1b1", "description": "Mia waving, close", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "the sun rising", "entities": ["the sun"]}]})


def _art(payload: str) -> Artifact:
    return Artifact.propose(type="timeline", owner="test", payload=payload, rationale="t")


def _build(tmp_path):
    script, board = parse_script(SCRIPT), parse_storyboard(STORYBOARD)
    assets = parse_assets(StubGenerator(64, 48).generate(script, board, tmp_path))
    timeline_json = Editor().assemble(board, assets)
    return board, assets, timeline_json


def test_editor_assembles_a_valid_contiguous_timeline(tmp_path):
    board, assets, tj = _build(tmp_path)
    assert SequenceCoverageGate(board).check(_art(tj)).passed
    assert TimelineIntegrityGate(assets).check(_art(tj)).passed


def test_multi_shot_beat_splits_its_audio_and_stays_in_sync(tmp_path):
    board, assets, tj = _build(tmp_path)
    timeline = parse_timeline(tj)
    audio = {a.beat_id: a.duration for a in assets.audio}
    # the two s1b1 shots together equal s1b1's narration; clips abut from zero
    s1b1 = [c for c in timeline.clips if c.beat_id == "s1b1"]
    assert len(s1b1) == 2
    assert abs(sum(c.duration for c in s1b1) - audio["s1b1"]) < 1e-3
    assert timeline.clips[0].start == 0
    for prev, nxt in zip(timeline.clips, timeline.clips[1:]):
        assert abs(nxt.start - (prev.start + prev.duration)) < 1e-3


def test_reordered_cut_fails_sequence_coverage(tmp_path):
    board, _assets, tj = _build(tmp_path)
    t = json.loads(tj)
    t["clips"][0], t["clips"][2] = t["clips"][2], t["clips"][0]  # shuffle the order
    res = SequenceCoverageGate(board).check(_art(json.dumps(t)))
    assert not res.passed and "order" in res.evidence


def test_gap_in_the_cut_fails_integrity(tmp_path):
    _board, assets, tj = _build(tmp_path)
    t = json.loads(tj)
    t["clips"][1]["start"] += 0.5  # punch a hole in the timeline
    res = TimelineIntegrityGate(assets).check(_art(json.dumps(t)))
    assert not res.passed and ("gap" in res.evidence or "overlap" in res.evidence)


def test_editor_agent_produces_a_timeline_artifact(tmp_path):
    board, assets, _tj = _build(tmp_path)
    art = EditorAgent().propose(board, assets)
    assert art.type == "timeline" and parse_timeline(art.payload).clips
