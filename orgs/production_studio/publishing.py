"""P25e — publishing: the timeline becomes a real, playable file, verified by format + integrity.

The Publisher renders the cut with ffmpeg: a video track from the image sequence (each shot held for
its clip's duration) and an audio track from the per-beat narration (each beat's clip plays once),
muxed together. They line up because TimelineIntegrity already guaranteed each beat's screen time
equals its narration audio. The gates then read the OUTPUT back with ffprobe — they trust the file,
not the renderer: PublishFormat checks the container/codecs/resolution match the target profile, and
OutputIntegrity checks the file decodes and its duration matches the timeline. ffmpeg is the seam, so
a different encoder can slot behind `Publisher` later.
"""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.run import Phase, emit_activity
from orgs.production_studio.assets import AssetSet
from orgs.production_studio.editing import Timeline
from orgs.production_studio.production import ProductionParseError


@dataclass
class PublishProfile:
    """The target the output must conform to — the platform spec, made checkable."""

    container: str = "mp4"
    vcodec: str = "h264"
    acodec: str = "aac"
    width: int = 1280
    height: int = 720
    fps: int = 24


class PublishError(RuntimeError):
    """ffmpeg failed to render the output."""


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise PublishError(f"{cmd[0]} failed: {proc.stderr.strip()[-400:]}")


def ffprobe_info(path: Path) -> dict[str, Any]:
    """Probe a media file → {format, streams}. Raises PublishError if it isn't decodable."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise PublishError(f"ffprobe could not read {path.name}: {proc.stderr.strip()[-200:]}")
    info: dict[str, Any] = json.loads(proc.stdout)
    return info


class Publisher(ABC):
    @abstractmethod
    def render(self, timeline: Timeline, assets: AssetSet, profile: PublishProfile, out_path: Path) -> None:
        raise NotImplementedError


class FfmpegPublisher(Publisher):
    """Renders the timeline to an MP4: image sequence (held per clip) + concatenated narration."""

    def render(self, timeline: Timeline, assets: AssetSet, profile: PublishProfile, out_path: Path) -> None:
        work = out_path.parent
        work.mkdir(parents=True, exist_ok=True)

        # Real motion when every shot has a generated clip; otherwise the held-still fallback. The
        # timeline (narration-driven, sync-checked) is the authority either way — the video conforms.
        clip_by_shot: dict[int, str] = {}
        for im in assets.images:
            if im.clip is not None:
                clip_by_shot[im.shot_index] = im.clip

        video = work / "_video.mp4"
        audio = work / "_audio.m4a"
        if all(c.shot_index in clip_by_shot for c in timeline.clips):
            self._render_clip_video(timeline, clip_by_shot, profile, work, video)
        else:
            self._render_still_video(timeline, profile, work, video)

        # audio: each beat's narration once, in first-appearance order (a clip's audio is its beat's).
        alist = work / "_audio.txt"
        seen: set[str] = set()
        alines = []
        for c in timeline.clips:
            if c.beat_id not in seen and c.audio:
                seen.add(c.beat_id)
                alines.append(f"file '{Path(c.audio).name}'")
        alist.write_text("\n".join(alines), encoding="utf-8")

        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(alist), "-c:a", "aac", str(audio)])
        _run(["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
              "-c:v", "copy", "-c:a", "copy", "-shortest", str(out_path)])

    def _render_still_video(self, timeline: Timeline, profile: PublishProfile,
                            work: Path, video: Path) -> None:
        # The concat demuxer resolves each `file` path relative to the LIST FILE's own directory, not
        # the cwd — so we write basenames (assets are siblings of the list here). A full cwd-relative
        # path doubled the prefix under a relative data dir (the hub's ./hub_data) and broke the render.
        # Held-still video: a concat list of images with per-clip durations (last image repeated so its
        # duration takes effect — a concat-demuxer requirement).
        vlist = work / "_video.txt"
        vlines = []
        for c in timeline.clips:
            vlines.append(f"file '{Path(c.image).name}'")
            vlines.append(f"duration {c.duration}")
        vlines.append(f"file '{Path(timeline.clips[-1].image).name}'")
        vlist.write_text("\n".join(vlines), encoding="utf-8")
        # image-with-durations concat is variable-frame-rate; -r would contradict -vsync vfr.
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(vlist), "-vsync", "vfr",
              "-vf", f"scale={profile.width}:{profile.height},format=yuv420p",
              "-c:v", "libx264", str(video)])

    def _render_clip_video(self, timeline: Timeline, clip_by_shot: dict[int, str],
                           profile: PublishProfile, work: Path, video: Path) -> None:
        # Fit each real clip to its narration-driven slot: freeze-pad the last frame if the clip is
        # shorter than the slot (tpad clone), trim with -t if longer, conforming fps/scale/pixfmt so the
        # segments concat cleanly. tpad's stop_duration is set to the full slot (always enough); -t then
        # cuts to exactly the slot length whether the source was shorter or longer.
        segs = []
        for idx, c in enumerate(timeline.clips):
            seg = work / f"_seg_{idx:03d}.mp4"
            _run(["ffmpeg", "-y", "-i", clip_by_shot[c.shot_index],
                  "-vf", (f"fps={profile.fps},scale={profile.width}:{profile.height},"
                          f"tpad=stop_mode=clone:stop_duration={c.duration},format=yuv420p"),
                  "-t", f"{c.duration}", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg)])
            segs.append(seg)
        clist = work / "_clips.txt"
        clist.write_text("\n".join(f"file '{s.name}'" for s in segs), encoding="utf-8")
        # re-encode on concat (not copy) so any timebase differences between segments are normalized.
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(clist),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)])


@dataclass
class PublishManifest:
    output: str
    profile: dict[str, Any]
    expected_duration: float


def parse_publish(payload: str) -> PublishManifest:
    try:
        obj: Any = json.loads(payload)
        return PublishManifest(str(obj["output"]), dict(obj["profile"]),
                               float(obj["expected_duration"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise ProductionParseError(f"publish manifest malformed: {exc}") from exc


class PublisherAgent:
    """Wraps the publisher as a proposer: renders the file, returns a manifest pointing at it."""

    role = "publisher"

    def __init__(self, publisher: Publisher, profile: PublishProfile) -> None:
        self.publisher = publisher
        self.profile = profile

    def propose(self, timeline: Timeline, assets: AssetSet, out_path: Path) -> Artifact:
        emit_activity(Phase.SYNTHESIZE, self.role, "rendering the final video…")
        self.publisher.render(timeline, assets, self.profile, out_path)
        manifest = json.dumps({"output": str(out_path), "profile": asdict(self.profile),
                               "expected_duration": timeline.total})
        return Artifact.propose(type="publish", owner="publisher", payload=manifest,
                                rationale=f"published {out_path.name}")


class PublishFormatGate(Gate):
    """HARD: the output conforms to the target profile — right container, codecs, and resolution."""

    name = "publish-format"
    determinism = Determinism.HARD

    def __init__(self, profile: PublishProfile) -> None:
        self.profile = profile

    def check(self, artifact: Artifact) -> GateResult:
        try:
            manifest = parse_publish(artifact.payload)
            info = ffprobe_info(Path(manifest.output))
        except (ProductionParseError, PublishError) as exc:
            return self._result(False, str(exc))
        streams = info.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        problems: list[str] = []
        if self.profile.container not in info.get("format", {}).get("format_name", ""):
            problems.append(f"container {info.get('format', {}).get('format_name')} != {self.profile.container}")
        if video is None:
            problems.append("no video stream")
        else:
            if video.get("codec_name") != self.profile.vcodec:
                problems.append(f"video codec {video.get('codec_name')} != {self.profile.vcodec}")
            if (video.get("width"), video.get("height")) != (self.profile.width, self.profile.height):
                problems.append(f"resolution {video.get('width')}x{video.get('height')} != {self.profile.width}x{self.profile.height}")
        if audio is None:
            problems.append("no audio stream")
        elif audio.get("codec_name") != self.profile.acodec:
            problems.append(f"audio codec {audio.get('codec_name')} != {self.profile.acodec}")
        if problems:
            return self._result(False, "; ".join(problems))
        return self._result(
            True, f"{self.profile.vcodec}/{self.profile.acodec} {self.profile.width}x{self.profile.height} {self.profile.container}"
        )


class OutputIntegrityGate(Gate):
    """HARD: the file decodes and its duration matches the timeline — not truncated or corrupt."""

    name = "output-integrity"
    determinism = Determinism.HARD

    def __init__(self, expected_duration: float, tolerance: float = 0.5) -> None:
        self.expected = expected_duration
        self.tolerance = tolerance

    def check(self, artifact: Artifact) -> GateResult:
        try:
            manifest = parse_publish(artifact.payload)
            info = ffprobe_info(Path(manifest.output))
        except (ProductionParseError, PublishError) as exc:
            return self._result(False, str(exc))
        try:
            dur = float(info.get("format", {}).get("duration", 0.0))
        except (ValueError, TypeError):
            return self._result(False, "output has no readable duration")
        if abs(dur - self.expected) > self.tolerance:
            return self._result(False, f"output is {dur:.2f}s, timeline is {self.expected:.2f}s")
        return self._result(True, f"decodes, {dur:.2f}s (matches the {self.expected:.2f}s timeline)")
