"""P25b — asset generation: the storyboard becomes real media, verified by integrity + coverage.

Each shot gets an image; each beat's narration gets an audio clip. Asset generation is a TOOL, not
a model proposal — the `AssetGenerator` seam wraps whatever produces the media (a deterministic stub
offline; a real image-gen + TTS engine later, behind the same interface). The artifact is a manifest
that points at the files on disk; the gates rule on it: COVERAGE (an asset for every shot and beat —
nothing missing) and INTEGRITY (every file is a real, decodable image/audio of the size/duration the
manifest claims). "Does it look good" is not asked here — that is the human tier (P25f).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from orgs.production_studio.media import (
    read_png_size,
    read_wav_duration,
    write_png,
    write_wav,
)
from orgs.production_studio.production import (
    ProductionParseError,
    Script,
    Storyboard,
    WORDS_PER_SECOND,
    script_beats,
)

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
_DURATION_TOLERANCE = 0.2  # seconds: the on-disk audio must match its manifest duration this closely


# --- the manifest (the asset-stage artifact) ---------------------------------------------

@dataclass
class ImageRef:
    shot_index: int
    beat_id: str
    path: str
    width: int
    height: int


@dataclass
class AudioRef:
    beat_id: str
    path: str
    duration: float


@dataclass
class AssetSet:
    images: list[ImageRef]
    audio: list[AudioRef]


def parse_assets(payload: str) -> AssetSet:
    try:
        obj: Any = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ProductionParseError(f"asset manifest not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProductionParseError("asset manifest must be a JSON object")
    try:
        images = [ImageRef(int(i["shot_index"]), str(i["beat_id"]), str(i["path"]),
                           int(i["width"]), int(i["height"])) for i in obj.get("images", [])]
        audio = [AudioRef(str(a["beat_id"]), str(a["path"]), float(a["duration"]))
                 for a in obj.get("audio", [])]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductionParseError(f"asset manifest malformed: {exc}") from exc
    return AssetSet(images=images, audio=audio)


# --- the seam: a generator produces the media + returns the manifest ----------------------

class AssetGenerator(ABC):
    """Produces an image per shot and audio per beat into `out_dir`, returns the manifest JSON.
    The stub is deterministic and offline; a real image-gen + TTS engine implements the same method."""

    @abstractmethod
    def generate(self, script: Script, storyboard: Storyboard, out_dir: Path) -> str:
        raise NotImplementedError


class StubGenerator(AssetGenerator):
    """Deterministic placeholders: a real PNG per shot (color seeded by the beat so shots differ)
    and a real WAV per beat sized to its narration's runtime. Proves the integrity/coverage gates
    with zero dependencies; swap in a real engine behind AssetGenerator later."""

    def __init__(self, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> None:
        self.width = width
        self.height = height

    @staticmethod
    def _color(seed: str) -> tuple[int, int, int]:
        h = abs(hash(seed))
        return (h & 0xFF, (h >> 8) & 0xFF, (h >> 16) & 0xFF)

    def generate(self, script: Script, storyboard: Storyboard, out_dir: Path) -> str:
        out_dir.mkdir(parents=True, exist_ok=True)
        images = []
        for i, shot in enumerate(storyboard.shots):
            p = out_dir / f"img_{i:03d}.png"
            write_png(p, self.width, self.height, self._color(shot.beat_id))
            images.append({"shot_index": i, "beat_id": shot.beat_id, "path": str(p),
                           "width": self.width, "height": self.height})
        audio = []
        for b in script_beats(script):
            seconds = max(0.5, len(b.narration.split()) / WORDS_PER_SECOND)
            p = out_dir / f"aud_{b.id}.wav"
            write_wav(p, seconds)
            audio.append({"beat_id": b.id, "path": str(p), "duration": round(seconds, 3)})
        return json.dumps({"images": images, "audio": audio})


class AssetGeneratorAgent:
    """Wraps a generator as a proposer in the cast's shape: it produces the manifest artifact the
    gates then verify. (No LLM — the 'proposal' is a tool call; the gates are still the authority.)"""

    role = "asset-generator"

    def __init__(self, generator: AssetGenerator) -> None:
        self.generator = generator

    def propose(self, script: Script, storyboard: Storyboard, out_dir: Path) -> Artifact:
        manifest = self.generator.generate(script, storyboard, out_dir)
        return Artifact.propose(type="assets", owner="asset-generator", payload=manifest,
                                rationale=f"assets for {len(storyboard.shots)} shot(s)")


# --- the gates ----------------------------------------------------------------------------

class AssetCoverageGate(Gate):
    """HARD: every shot has an image and every beat has narration audio — the production isn't
    missing a frame or a line."""

    name = "asset-coverage"
    determinism = Determinism.HARD

    def __init__(self, script: Script, storyboard: Storyboard) -> None:
        self.shot_count = len(storyboard.shots)
        self.beat_ids = {b.id for b in script_beats(script)}

    def check(self, artifact: Artifact) -> GateResult:
        try:
            assets = parse_assets(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"assets not usable: {exc}")
        have_shots = {im.shot_index for im in assets.images}
        missing_img = [i for i in range(self.shot_count) if i not in have_shots]
        have_audio = {a.beat_id for a in assets.audio}
        missing_audio = sorted(self.beat_ids - have_audio)
        problems = []
        if missing_img:
            problems.append(f"shots with no image: {', '.join(map(str, missing_img))}")
        if missing_audio:
            problems.append(f"beats with no audio: {', '.join(missing_audio)}")
        if problems:
            return self._result(False, "; ".join(problems))
        return self._result(
            True, f"{self.shot_count} shot image(s) + {len(self.beat_ids)} beat audio clip(s), all present"
        )


class AssetIntegrityGate(Gate):
    """HARD: every manifest file is a real, decodable asset of the size/duration it claims — no
    corrupt, empty, or mislabeled media."""

    name = "asset-integrity"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            assets = parse_assets(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"assets not usable: {exc}")
        problems: list[str] = []
        for im in assets.images:
            p = Path(im.path)
            if not p.exists():
                problems.append(f"missing image {p.name}")
                continue
            try:
                w, h = read_png_size(p)
            except ValueError as exc:
                problems.append(f"{p.name}: {exc}")
                continue
            if (w, h) != (im.width, im.height):
                problems.append(f"{p.name}: is {w}x{h}, manifest says {im.width}x{im.height}")
        for a in assets.audio:
            p = Path(a.path)
            if not p.exists():
                problems.append(f"missing audio {p.name}")
                continue
            try:
                dur = read_wav_duration(p)
            except (ValueError, EOFError, OSError) as exc:
                problems.append(f"{p.name}: unreadable ({exc})")
                continue
            if abs(dur - a.duration) > _DURATION_TOLERANCE:
                problems.append(f"{p.name}: is {dur:.2f}s, manifest says {a.duration:.2f}s")
        if problems:
            shown = "; ".join(problems[:6]) + (" …" if len(problems) > 6 else "")
            return self._result(False, shown)
        n = len(assets.images) + len(assets.audio)
        return self._result(True, f"all {n} asset file(s) decode and match the manifest")
