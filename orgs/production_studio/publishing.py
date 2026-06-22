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

        # The concat demuxer resolves each `file` path relative to the LIST FILE's own directory,
        # not the cwd — so we write basenames (assets are always siblings of the list here). Writing
        # the full cwd-relative path doubled the prefix when the data dir was relative (e.g. the hub's
        # ./hub_data), producing .../<id>/hub_data/productions/<id>/img.png and a missing-file error.

        # video: a concat-demuxer list of images with per-clip durations (last image repeated so its
        # duration takes effect — a known concat-demuxer requirement).
        vlist = work / "_video.txt"
        vlines = []
        for c in timeline.clips:
            vlines.append(f"file '{Path(c.image).name}'")
            vlines.append(f"duration {c.duration}")
        vlines.append(f"file '{Path(timeline.clips[-1].image).name}'")
        vlist.write_text("\n".join(vlines), encoding="utf-8")

        # audio: each beat's narration once, in first-appearance order (a clip's audio is its beat's).
        alist = work / "_audio.txt"
        seen: set[str] = set()
        alines = []
        for c in timeline.clips:
            if c.beat_id not in seen and c.audio:
                seen.add(c.beat_id)
                alines.append(f"file '{Path(c.audio).name}'")
        alist.write_text("\n".join(alines), encoding="utf-8")

        video = work / "_video.mp4"
        audio = work / "_audio.m4a"
        # image-with-durations concat is variable-frame-rate; -r would contradict -vsync vfr, so the
        # clip durations alone drive timing (the format gate checks codec/resolution, not fps).
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(vlist), "-vsync", "vfr",
              "-vf", f"scale={profile.width}:{profile.height},format=yuv420p",
              "-c:v", "libx264", str(video)])
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(alist), "-c:a", "aac", str(audio)])
        _run(["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
              "-c:v", "copy", "-c:a", "copy", "-shortest", str(out_path)])


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
