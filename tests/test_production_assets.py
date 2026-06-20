"""P25b — asset generation, verified by integrity + coverage.

The stub writes REAL png/wav files (stdlib only), so the gates check facts: a decodable image of
the claimed size for every shot, a playable clip of the claimed length for every beat. Coverage
catches a missing frame; integrity catches a corrupt or mislabeled file. Driven offline.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.production_studio.assets import (
    AssetConsistencyGate,
    AssetCoverageGate,
    AssetIntegrityGate,
    StubGenerator,
)
from orgs.production_studio.media import (
    read_png_size,
    read_wav_duration,
    write_png,
    write_wav,
)
from orgs.production_studio.pipeline import build_production
from orgs.production_studio.production import parse_script, parse_storyboard

SCRIPT = json.dumps({"scenes": [
    {"heading": "A", "beats": [
        {"narration": "Mia looks up at the wide blue sky and wonders why it is blue.", "entities": ["Mia"]},
        {"narration": "The sun pours its light down across the whole town.", "entities": ["the sun"]}]},
    {"heading": "B", "beats": [
        {"narration": "Tiny air molecules scatter the blue light everywhere.", "entities": ["air molecules"]}]},
]})  # beats: s1b1, s1b2, s2b1
STORYBOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "Mia on the grass", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "the sun beaming", "entities": ["the sun"]},
    {"beat_id": "s2b1", "description": "molecules scattering light", "entities": ["air molecules"]},
]})

CONCEPT = json.dumps({
    "title": "Why the Sky is Blue", "logline": "a kid learns why the sky is blue",
    "audience": "kids", "tone": "warm", "target_seconds": 20,
    "entities": ["Mia", "the sun", "air molecules"],
})


def _art(payload: str) -> Artifact:
    return Artifact.propose(type="assets", owner="test", payload=payload, rationale="t")


# --- the media helpers actually round-trip ------------------------------------------------

def test_png_and_wav_round_trip(tmp_path):
    img = tmp_path / "x.png"
    write_png(img, 64, 48, (10, 20, 30))
    assert read_png_size(img) == (64, 48)
    aud = tmp_path / "x.wav"
    write_wav(aud, 1.5)
    assert abs(read_wav_duration(aud) - 1.5) < 0.05


# --- the gates ----------------------------------------------------------------------------

def _generate(tmp_path) -> str:
    script, board = parse_script(SCRIPT), parse_storyboard(STORYBOARD)
    return StubGenerator(64, 48).generate(script, board, tmp_path)


def test_full_assets_pass_coverage_and_integrity(tmp_path):
    manifest = _generate(tmp_path)
    script, board = parse_script(SCRIPT), parse_storyboard(STORYBOARD)
    assert AssetCoverageGate(script, board).check(_art(manifest)).passed
    assert AssetIntegrityGate().check(_art(manifest)).passed


def test_missing_image_fails_coverage(tmp_path):
    manifest = json.loads(_generate(tmp_path))
    manifest["images"] = manifest["images"][:-1]  # drop the last shot's image
    script, board = parse_script(SCRIPT), parse_storyboard(STORYBOARD)
    res = AssetCoverageGate(script, board).check(_art(json.dumps(manifest)))
    assert not res.passed and "no image" in res.evidence


def test_corrupt_file_fails_integrity(tmp_path):
    manifest = json.loads(_generate(tmp_path))
    bad = manifest["images"][0]["path"]
    with open(bad, "wb") as f:
        f.write(b"not a real png")  # same path, now corrupt
    res = AssetIntegrityGate().check(_art(json.dumps(manifest)))
    assert not res.passed and "PNG" in res.evidence


def test_missing_file_fails_integrity(tmp_path):
    import os
    manifest = json.loads(_generate(tmp_path))
    os.remove(manifest["audio"][0]["path"])
    res = AssetIntegrityGate().check(_art(json.dumps(manifest)))
    assert not res.passed and "missing audio" in res.evidence


# --- P25c: visual consistency -------------------------------------------------------------

_RECUR_SCRIPT = json.dumps({"scenes": [{"heading": "A", "beats": [
    {"narration": "Mia waves hello to the whole sleepy town below.", "entities": ["Mia"]},
    {"narration": "Mia walks down the sunny street past the shops.", "entities": ["Mia"]}]}]})
_RECUR_BOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "Mia waving", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "Mia walking", "entities": ["Mia"]}]})


def test_recurring_entity_is_drawn_consistently(tmp_path):
    script, board = parse_script(_RECUR_SCRIPT), parse_storyboard(_RECUR_BOARD)
    manifest = StubGenerator(64, 48).generate(script, board, tmp_path)
    assert AssetConsistencyGate().check(_art(manifest)).passed
    # consistency by construction: the same entity set renders byte-identical pixels
    paths = [im["path"] for im in json.loads(manifest)["images"]]
    assert open(paths[0], "rb").read() == open(paths[1], "rb").read()


def test_drifting_reference_fails_consistency(tmp_path):
    script, board = parse_script(_RECUR_SCRIPT), parse_storyboard(_RECUR_BOARD)
    manifest = json.loads(StubGenerator(64, 48).generate(script, board, tmp_path))
    manifest["images"][1]["entity_refs"]["Mia"] = "ref:someone-else"  # the character changes look
    res = AssetConsistencyGate().check(_art(json.dumps(manifest)))
    assert not res.passed and "Mia" in res.evidence


# --- the whole chain, with assets ---------------------------------------------------------

def test_production_with_assets_ships_four_stages(tmp_path):
    provider = ScriptedProvider(
        {"concept": CONCEPT, "scriptwriter": SCRIPT, "storyboard-artist": STORYBOARD})
    res = build_production("explain why the sky is blue", provider, MemoryStore(tmp_path),
                           asset_generator=StubGenerator(64, 48), asset_dir=tmp_path / "assets")
    assert res.accepted
    assert [o.artifact.type for o in res.outcomes] == ["concept", "script", "storyboard", "assets"]
    assert all(o.accepted for o in res.outcomes)
