"""Slice 2 — real generated video behind the asset seam, verified by clip-integrity.

LtxGenerator turns each shot into a real clip (here via the offline ScriptedVideoBackend, so no GPU
or model download) and extracts a frame as the still, so the existing image gates stay honest while
the new ClipIntegrityGate checks the clips themselves. The gate is additive: a stills-only manifest
(the stub/say path) passes it as a no-op, so nothing about the proven chain changes until real video
is present.
"""

from __future__ import annotations

import json
import shutil

import pytest

from engine.artifact import Artifact
from orgs.production_studio.assets import (
    AssetConsistencyGate,
    AssetCoverageGate,
    AssetIntegrityGate,
    ClipIntegrityGate,
    LtxGenerator,
    StubGenerator,
)
from orgs.production_studio.media import write_png
from orgs.production_studio.production import parse_script, parse_storyboard
from orgs.production_studio.tts import SilentTTSBackend
from orgs.production_studio.video import ScriptedVideoBackend

has_ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

SCRIPT = json.dumps({"scenes": [{"heading": "A", "beats": [
    {"narration": "Mia waves hello to the sleepy town below.", "entities": ["Mia"]},
    {"narration": "Mia walks down the sunny street past the shops.", "entities": ["Mia"]}]}]})
STORYBOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "Mia waving", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "Mia walking", "entities": ["Mia"]}]})


def _art(payload: str) -> Artifact:
    return Artifact.propose(type="assets", owner="test", payload=payload, rationale="t")


def _clip_manifest(tmp_path, n: int = 2):
    """Build a manifest with real (scripted) clips + stand-in frames — exercises the gate directly,
    without needing macOS `say` for the audio half."""
    backend = ScriptedVideoBackend()
    images = []
    for i in range(n):
        cp = tmp_path / f"img_{i:03d}.mp4"
        clip = backend.generate_clip("x", cp, seconds=1.0, fps=24, width=64, height=64, seed=i)
        png = tmp_path / f"img_{i:03d}.png"
        write_png(png, clip.width, clip.height)
        images.append({"shot_index": i, "beat_id": f"b{i}", "path": str(png),
                       "width": clip.width, "height": clip.height, "entity_refs": {},
                       "clip": str(cp), "clip_duration": clip.duration})
    return {"images": images, "audio": []}


# --- ClipIntegrityGate (only needs ffmpeg) ------------------------------------------------

def test_clip_integrity_is_a_noop_without_clips(tmp_path):
    # the stub path produces no clips → the gate passes and constrains nothing
    manifest = StubGenerator(64, 48).generate(parse_script(SCRIPT), parse_storyboard(STORYBOARD), tmp_path)
    res = ClipIntegrityGate().check(_art(manifest))
    assert res.passed and "stills only" in res.evidence


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg/ffprobe")
def test_clip_integrity_passes_on_real_clips(tmp_path):
    manifest = _clip_manifest(tmp_path)
    res = ClipIntegrityGate().check(_art(json.dumps(manifest)))
    assert res.passed and "2 generated clip(s)" in res.evidence


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg/ffprobe")
def test_clip_integrity_fails_on_corrupt_clip(tmp_path):
    manifest = _clip_manifest(tmp_path)
    with open(manifest["images"][0]["clip"], "wb") as f:
        f.write(b"not a real mp4")  # same path, now undecodable
    res = ClipIntegrityGate().check(_art(json.dumps(manifest)))
    assert not res.passed


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg/ffprobe")
def test_clip_integrity_fails_on_duration_mismatch(tmp_path):
    manifest = _clip_manifest(tmp_path)
    manifest["images"][0]["clip_duration"] = 99.0  # claim a runtime the file doesn't have
    res = ClipIntegrityGate().check(_art(json.dumps(manifest)))
    assert not res.passed and "manifest says 99.00s" in res.evidence


# --- LtxGenerator end to end (needs ffmpeg for video + `say` for narration) ---------------

@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg/ffprobe")
def test_ltx_generator_produces_verified_clips_and_frames(tmp_path):
    gen = LtxGenerator(ScriptedVideoBackend(), tts=SilentTTSBackend(), width=64, height=64, seconds=1.0)
    manifest = json.loads(gen.generate(parse_script(SCRIPT), parse_storyboard(STORYBOARD), tmp_path))
    script, board = parse_script(SCRIPT), parse_storyboard(STORYBOARD)
    # every shot carries a real clip AND a real extracted frame; both halves of the manifest are real
    assert all(im.get("clip") for im in manifest["images"])
    art = _art(json.dumps(manifest))
    assert AssetCoverageGate(script, board).check(art).passed
    assert AssetIntegrityGate().check(art).passed          # the extracted PNG frames decode
    assert AssetConsistencyGate().check(art).passed        # Mia requested with one reference throughout
    assert ClipIntegrityGate().check(art).passed           # the clips decode + match the manifest
