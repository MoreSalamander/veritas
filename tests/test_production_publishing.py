"""P25e — publishing, verified by format + integrity.

The timeline is rendered to a real MP4 with ffmpeg, then the gates read the OUTPUT back with ffprobe
— they trust the file, not the renderer. Requires ffmpeg/ffprobe on PATH (skipped otherwise), same
way the web org's tests require a real browser. A small 320x240 profile keeps the encode quick.
"""

from __future__ import annotations

import json
import shutil

import pytest

from engine.artifact import Artifact
from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.production_studio.assets import StubGenerator, parse_assets
from orgs.production_studio.editing import Editor, parse_timeline
from orgs.production_studio.pipeline import build_production
from orgs.production_studio.production import parse_script, parse_storyboard
from orgs.production_studio.publishing import (
    FfmpegPublisher,
    OutputIntegrityGate,
    PublishFormatGate,
    PublisherAgent,
    PublishProfile,
)

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg/ffprobe")

SCRIPT = json.dumps({"scenes": [{"heading": "A", "beats": [
    {"narration": "Mia waves hello to the whole sleepy little town below her today.", "entities": ["Mia"]},
    {"narration": "The sun climbs slowly over the quiet rooftops.", "entities": ["the sun"]}]}]})
STORYBOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "Mia waving wide", "entities": ["Mia"]},
    {"beat_id": "s1b1", "description": "Mia waving close", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "the sun rising", "entities": ["the sun"]}]})
CONCEPT = json.dumps({"title": "Morning", "logline": "a small town wakes up", "audience": "kids",
                      "tone": "warm", "target_seconds": 15, "entities": ["Mia", "the sun"]})
SMALL = PublishProfile(width=320, height=240, fps=24)


def _art(payload: str) -> Artifact:
    return Artifact.propose(type="publish", owner="test", payload=payload, rationale="t")


def _render(tmp_path):
    script, board = parse_script(SCRIPT), parse_storyboard(STORYBOARD)
    assets = parse_assets(StubGenerator(320, 240).generate(script, board, tmp_path))
    timeline = parse_timeline(Editor().assemble(board, assets))
    art = PublisherAgent(FfmpegPublisher(), SMALL).propose(timeline, assets, tmp_path / "out.mp4")
    return timeline, art


def test_render_passes_format_and_integrity(tmp_path):
    timeline, art = _render(tmp_path)
    assert PublishFormatGate(SMALL).check(art).passed
    assert OutputIntegrityGate(timeline.total).check(art).passed


def test_wrong_resolution_fails_format(tmp_path):
    _timeline, art = _render(tmp_path)
    res = PublishFormatGate(PublishProfile(width=1920, height=1080)).check(art)
    assert not res.passed and "resolution" in res.evidence


def test_missing_output_fails_integrity(tmp_path):
    res = OutputIntegrityGate(10.0).check(_art(json.dumps(
        {"output": str(tmp_path / "nope.mp4"), "profile": {}, "expected_duration": 10.0})))
    assert not res.passed


def test_render_works_from_a_relative_data_dir(tmp_path, monkeypatch):
    # Regression: the hub launches with a RELATIVE data dir (./hub_data), so asset paths were
    # cwd-relative. The concat demuxer resolves its entries relative to the LIST FILE's dir, which
    # doubled the prefix (.../<id>/hub_data/productions/<id>/img.png) and broke every hub render.
    # The absolute tmp_path tests above never exercised this. Render under a relative path here.
    monkeypatch.chdir(tmp_path)
    work = __import__("pathlib").Path("rel_data/productions/x")  # relative to cwd, like the hub
    timeline, art = _render(work)
    assert PublishFormatGate(SMALL).check(art).passed
    assert OutputIntegrityGate(timeline.total).check(art).passed


def _clip_assets(tmp_path, script, board, profile):
    """Build an AssetSet whose shots carry REAL (scripted) video clips of a fixed 1.5 s — different
    from the narration-driven slots so the publisher must both trim (beats with 2 shots → 1.0 s slots)
    and freeze-pad (the 1-shot beat → a 2.0 s slot)."""
    from orgs.production_studio.media import write_png, write_wav
    from orgs.production_studio.production import script_beats
    from orgs.production_studio.video import ScriptedVideoBackend
    backend = ScriptedVideoBackend()
    images = []
    for i, shot in enumerate(board.shots):
        cp = tmp_path / f"img_{i:03d}.mp4"
        clip = backend.generate_clip("x", cp, seconds=1.5, fps=profile.fps,
                                     width=profile.width, height=profile.height, seed=i)
        png = tmp_path / f"img_{i:03d}.png"
        write_png(png, clip.width, clip.height)
        images.append({"shot_index": i, "beat_id": shot.beat_id, "path": str(png),
                       "width": clip.width, "height": clip.height, "entity_refs": {},
                       "clip": str(cp), "clip_duration": clip.duration})
    audio = []
    for b in script_beats(script):
        wp = tmp_path / f"aud_{b.id}.wav"
        write_wav(wp, 2.0)
        audio.append({"beat_id": b.id, "path": str(wp), "duration": 2.0})
    return parse_assets(json.dumps({"images": images, "audio": audio}))


def test_real_clips_publish_with_motion_and_stay_in_sync(tmp_path):
    script, board = parse_script(SCRIPT), parse_storyboard(STORYBOARD)
    assets = _clip_assets(tmp_path, script, board, SMALL)
    timeline = parse_timeline(Editor().assemble(board, assets))
    art = PublisherAgent(FfmpegPublisher(), SMALL).propose(timeline, assets, tmp_path / "out.mp4")
    # the cut used the real clips (trim + freeze-pad to each slot) and still conforms + matches the timeline
    assert PublishFormatGate(SMALL).check(art).passed
    assert OutputIntegrityGate(timeline.total).check(art).passed


def test_full_production_publishes_six_stages(tmp_path):
    provider = ScriptedProvider(
        {"concept": CONCEPT, "scriptwriter": SCRIPT, "storyboard-artist": STORYBOARD})
    res = build_production("a small town morning", provider, MemoryStore(tmp_path),
                           asset_generator=StubGenerator(320, 240), asset_dir=tmp_path / "a",
                           publisher=FfmpegPublisher(), profile=SMALL)
    assert res.accepted
    assert [o.artifact.type for o in res.outcomes] == \
        ["concept", "script", "storyboard", "assets", "timeline", "publish"]
