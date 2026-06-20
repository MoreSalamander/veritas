"""P25d — editing/assembly: the shots + narration become a timeline, verified by conformance +
temporal integrity.

The editor is a deterministic tool (no model): it lays the storyboard shots out in order, gives each
shot its share of its beat's narration time (a beat with two shots splits that beat's audio between
them), and chains them with no gaps. The gates rule on the result: SequenceCoverage (every shot,
in storyboard order, exactly once) and TimelineIntegrity (clips are contiguous from zero, each beat's
screen time equals its narration audio — audio/visual stay in sync — and the total adds up).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from orgs.production_studio.assets import AssetSet
from orgs.production_studio.production import ProductionParseError, Storyboard

_SYNC_TOLERANCE = 0.05   # seconds: a beat's screen time must match its narration audio this closely
_CHAIN_TOLERANCE = 1e-3  # seconds: clips must abut (no gap/overlap) within this


@dataclass
class Clip:
    shot_index: int
    beat_id: str
    image: str
    audio: str
    start: float
    duration: float


@dataclass
class Timeline:
    clips: list[Clip]
    total: float


def parse_timeline(payload: str) -> Timeline:
    try:
        obj: Any = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ProductionParseError(f"timeline not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProductionParseError("timeline must be a JSON object")
    try:
        clips = [Clip(int(c["shot_index"]), str(c["beat_id"]), str(c["image"]), str(c["audio"]),
                      float(c["start"]), float(c["duration"])) for c in obj.get("clips", [])]
        total = float(obj.get("total", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductionParseError(f"timeline malformed: {exc}") from exc
    if not clips:
        raise ProductionParseError("timeline has no clips")
    return Timeline(clips=clips, total=total)


class Editor:
    """Assembles the timeline deterministically from the storyboard order + the asset manifest."""

    def assemble(self, storyboard: Storyboard, assets: AssetSet) -> str:
        audio_dur = {a.beat_id: a.duration for a in assets.audio}
        audio_path = {a.beat_id: a.path for a in assets.audio}
        image_path = {im.shot_index: im.path for im in assets.images}
        shots_per_beat: dict[str, int] = {}
        for shot in storyboard.shots:
            shots_per_beat[shot.beat_id] = shots_per_beat.get(shot.beat_id, 0) + 1

        clips = []
        cursor = 0.0
        for i, shot in enumerate(storyboard.shots):
            dur = audio_dur.get(shot.beat_id, 0.0) / shots_per_beat[shot.beat_id]
            clips.append({"shot_index": i, "beat_id": shot.beat_id,
                          "image": image_path.get(i, ""), "audio": audio_path.get(shot.beat_id, ""),
                          "start": round(cursor, 6), "duration": round(dur, 6)})
            cursor += dur
        return json.dumps({"clips": clips, "total": round(cursor, 6)})


class EditorAgent:
    """Wraps the editor as a proposer (a tool call, not a model proposal); the gates are authority."""

    role = "editor"

    def propose(self, storyboard: Storyboard, assets: AssetSet) -> Artifact:
        payload = Editor().assemble(storyboard, assets)
        return Artifact.propose(type="timeline", owner="editor",
                                payload=payload, rationale="assembled cut")


class SequenceCoverageGate(Gate):
    """HARD: the timeline contains every shot, exactly once, in storyboard order — nothing dropped,
    reordered, or duplicated in the cut."""

    name = "sequence-coverage"
    determinism = Determinism.HARD

    def __init__(self, storyboard: Storyboard) -> None:
        self.expected = list(range(len(storyboard.shots)))

    def check(self, artifact: Artifact) -> GateResult:
        try:
            timeline = parse_timeline(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"timeline not usable: {exc}")
        got = [c.shot_index for c in timeline.clips]
        if got != self.expected:
            return self._result(False, f"shot order is {got}, expected {self.expected}")
        return self._result(True, f"all {len(self.expected)} shot(s) in storyboard order")


class TimelineIntegrityGate(Gate):
    """HARD: the cut is contiguous from zero (no gaps/overlaps), every clip has real duration, the
    total adds up, and each beat's screen time equals its narration audio (audio/visual in sync)."""

    name = "timeline-integrity"
    determinism = Determinism.HARD

    def __init__(self, assets: AssetSet) -> None:
        self.audio_dur = {a.beat_id: a.duration for a in assets.audio}

    def check(self, artifact: Artifact) -> GateResult:
        try:
            timeline = parse_timeline(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"timeline not usable: {exc}")
        problems: list[str] = []
        cursor = 0.0
        per_beat: dict[str, float] = {}
        for c in timeline.clips:
            if c.duration <= 0:
                problems.append(f"clip {c.shot_index} has no duration")
            if abs(c.start - cursor) > _CHAIN_TOLERANCE:
                problems.append(f"gap/overlap at clip {c.shot_index} (starts {c.start:.3f}, expected {cursor:.3f})")
            cursor += c.duration
            per_beat[c.beat_id] = per_beat.get(c.beat_id, 0.0) + c.duration
        if abs(timeline.total - cursor) > _CHAIN_TOLERANCE:
            problems.append(f"total {timeline.total:.3f} != sum of clips {cursor:.3f}")
        for beat, screen in per_beat.items():
            want = self.audio_dur.get(beat)
            if want is not None and abs(screen - want) > _SYNC_TOLERANCE:
                problems.append(f"beat {beat} screen time {screen:.2f}s != narration {want:.2f}s")
        if problems:
            shown = "; ".join(problems[:6]) + (" …" if len(problems) > 6 else "")
            return self._result(False, shown)
        return self._result(
            True, f"{len(timeline.clips)} clip(s), contiguous, {timeline.total:.1f}s, audio in sync"
        )
