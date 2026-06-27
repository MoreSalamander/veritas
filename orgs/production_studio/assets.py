"""P25b — asset generation: the storyboard becomes real media, verified by integrity + coverage.

Each shot gets an image; each beat's narration gets an audio clip. Asset generation is a TOOL, not
a model proposal — the `AssetGenerator` seam wraps whatever produces the media (a deterministic stub
offline; a real image-gen + TTS engine later, behind the same interface). The artifact is a manifest
that points at the files on disk; the gates rule on it: COVERAGE (an asset for every shot and beat —
nothing missing) and INTEGRITY (every file is a real, decodable image/audio of the size/duration the
manifest claims). "Does it look good" is not asked here — that is the human tier (P25f).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.run import Phase, emit_activity
from orgs.production_studio.media import (
    read_png_size,
    read_wav_duration,
    write_png,
    write_wav,
)
from orgs.production_studio.production import (
    Beat,
    ProductionParseError,
    Script,
    Shot,
    Storyboard,
    WORDS_PER_SECOND,
    _norm,
    script_beats,
)
from orgs.production_studio.video import VideoBackend, VideoError, probe_clip, seed_for

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
_DURATION_TOLERANCE = 0.2  # seconds: the on-disk audio must match its manifest duration this closely
_CLIP_DURATION_TOLERANCE = 0.5  # seconds: a generated clip's runtime can drift this far from its claim

# LTX video defaults, calibrated live on an M4 Pro / 24 GB: 768x512 fits with offload (the still
# 1280x720 would OOM the video model), and a deterministic style suffix turns a terse shot description
# into the detailed, sharpness-cued prompt LTX needs — verified that "sharp focus / bright / detailed"
# yields a crisp subject where a vague prompt (or "shallow depth of field") renders soft and hazy.
LTX_VIDEO_WIDTH = 768
LTX_VIDEO_HEIGHT = 512
LTX_STYLE_SUFFIX = ("sharp focus, highly detailed, vivid natural colors, bright natural lighting, "
                    "photorealistic, smooth natural motion, cinematic")


def reference_id(entity: str) -> str:
    """The pinned visual identity for an entity — decided once, reused everywhere it appears, so the
    character looks the same shot to shot. A real engine would map this to a seed / LoRA / reference
    image; the stub maps it to a stable color. Either way, the gate checks it never drifts."""
    return f"ref:{_norm(entity)}"


def reference_color(entity: str) -> tuple[int, int, int]:
    """A stable color for an entity's reference (hashlib, not hash(), so it's reproducible)."""
    d = hashlib.md5(_norm(entity).encode()).digest()
    return (d[0], d[1], d[2])


# --- the manifest (the asset-stage artifact) ---------------------------------------------

@dataclass
class ImageRef:
    shot_index: int
    beat_id: str
    path: str
    width: int
    height: int
    entity_refs: dict[str, str] = field(default_factory=dict)  # entity -> the reference it was drawn with
    clip: str | None = None          # the real video clip for this shot (None = still only)
    clip_duration: float | None = None  # the clip's measured runtime, for the integrity gate


@dataclass
class ImageWrite:
    """What a generator wrote for one shot — its dimensions, and optionally a video clip alongside the
    still. The default path produces just a still; the LTX path produces a clip and extracts a frame."""

    width: int
    height: int
    clip: str | None = None
    clip_duration: float | None = None


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
                           int(i["width"]), int(i["height"]),
                           {str(k): str(v) for k, v in dict(i.get("entity_refs", {})).items()},
                           (str(i["clip"]) if i.get("clip") else None),
                           (float(i["clip_duration"]) if i.get("clip_duration") is not None else None))
                  for i in obj.get("images", [])]
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
    def _shot_color(entities: list[str]) -> tuple[int, int, int]:
        # blend the entities' reference colors — the image is a pure function of WHO is in it, so a
        # character contributes the same color in every shot (consistency by construction).
        if not entities:
            return (120, 120, 120)
        cols = [reference_color(e) for e in entities]
        return tuple(sum(c[k] for c in cols) // len(cols) for k in range(3))  # type: ignore[return-value]

    def _write_audio(self, beat: Beat, path: Path) -> float:
        """Silent placeholder sized to the narration's estimated runtime. Subclasses override to
        produce real speech; the returned duration is what the manifest records."""
        seconds = max(0.5, len(beat.narration.split()) / WORDS_PER_SECOND)
        write_wav(path, seconds)
        return round(seconds, 3)

    def _write_image(self, shot: Shot, path: Path) -> ImageWrite:
        """Write the still for a shot. Subclasses override to render real video and extract a frame;
        the default is a solid-color PNG keyed to the shot's entities (consistency by construction)."""
        write_png(path, self.width, self.height, self._shot_color(shot.entities))
        return ImageWrite(self.width, self.height)

    def generate(self, script: Script, storyboard: Storyboard, out_dir: Path) -> str:
        out_dir.mkdir(parents=True, exist_ok=True)
        images = []
        for i, shot in enumerate(storyboard.shots):
            p = out_dir / f"img_{i:03d}.png"
            w = self._write_image(shot, p)
            entry: dict[str, Any] = {
                "shot_index": i, "beat_id": shot.beat_id, "path": str(p),
                "width": w.width, "height": w.height,
                "entity_refs": {e: reference_id(e) for e in shot.entities},
            }
            if w.clip is not None:
                entry["clip"] = w.clip
                entry["clip_duration"] = w.clip_duration
            images.append(entry)
        audio = []
        for b in script_beats(script):
            p = out_dir / f"aud_{b.id}.wav"
            duration = self._write_audio(b, p)
            audio.append({"beat_id": b.id, "path": str(p), "duration": duration})
        return json.dumps({"images": images, "audio": audio})


class SayGenerator(StubGenerator):
    """Real spoken narration via macOS `say` (zero dependencies); visuals stay placeholder until an
    image engine is wired behind the seam. The audio is genuine speech of each beat's narration, and
    the manifest records its actual measured duration so the timeline stays in sync."""

    def __init__(self, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT,
                 voice: str | None = None) -> None:
        super().__init__(width, height)
        self.voice = voice

    def _write_audio(self, beat: Beat, path: Path) -> float:
        argv = ["say", "-o", str(path), "--data-format=LEI16@22050"]
        if self.voice:
            argv += ["-v", self.voice]
        argv.append(beat.narration.strip() or " ")
        subprocess.run(argv, check=True, capture_output=True, timeout=120)
        return round(read_wav_duration(path), 3)


def _extract_frame(clip_path: Path, png_path: Path) -> None:
    """Pull the first frame of a clip into a PNG (ffmpeg) so the still contract stays honest — the
    image the gates inspect is a real frame of the real generated video, not a separate render."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip_path), "-frames:v", "1", "-update", "1", str(png_path)],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise VideoError(f"could not extract a frame from {clip_path.name}: {proc.stderr.strip()[-200:]}")


class LtxGenerator(SayGenerator):
    """Real generated video per shot via a `VideoBackend` (LTX locally, or a cloud backend). Each shot
    becomes a short clip; its first frame is extracted as the PNG so the existing image contract stays
    honest (a real, decodable frame), and the clip + its measured duration are recorded in the manifest
    for the clip-integrity gate and downstream editing. Narration is real speech (inherited from Say).
    The seed is derived from the shot's entities so a recurring cast is rendered with a stable identity
    request (the pixel-level guarantee is the perceptual gate, a later rung)."""

    def __init__(
        self,
        backend: VideoBackend,
        width: int = LTX_VIDEO_WIDTH,
        height: int = LTX_VIDEO_HEIGHT,
        voice: str | None = None,
        seconds: float = 2.0,
        fps: int = 24,
        style: str = LTX_STYLE_SUFFIX,
    ) -> None:
        super().__init__(width, height, voice)
        self.backend = backend
        self.seconds = seconds
        self.fps = fps
        self.style = style

    def _write_image(self, shot: Shot, path: Path) -> ImageWrite:
        clip_path = path.with_suffix(".mp4")
        base = shot.description.strip() or " ".join(shot.entities) or "a scene"
        prompt = f"{base}. {self.style}" if self.style else base
        clip = self.backend.generate_clip(
            prompt, clip_path,
            seconds=self.seconds, fps=self.fps, width=self.width, height=self.height,
            seed=seed_for(shot.entities),
        )
        _extract_frame(clip_path, path)  # the PNG is a real frame of the real clip
        return ImageWrite(clip.width, clip.height, clip=str(clip_path), clip_duration=clip.duration)


class AssetGeneratorAgent:
    """Wraps a generator as a proposer in the cast's shape: it produces the manifest artifact the
    gates then verify. (No LLM — the 'proposal' is a tool call; the gates are still the authority.)"""

    role = "asset-generator"

    def __init__(self, generator: AssetGenerator) -> None:
        self.generator = generator

    def propose(self, script: Script, storyboard: Storyboard, out_dir: Path) -> Artifact:
        emit_activity(Phase.SYNTHESIZE, self.role, "rendering images + narration…")
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


class AssetConsistencyGate(Gate):
    """HARD: each entity is REQUESTED with ONE pinned reference across every shot it appears in — the
    same seed/reference is asked for each time, so the production can't silently re-roll a character's
    identity scene to scene. This is the referential-integrity guarantee at the *request* level, which
    is all metadata can prove. Whether the resulting PIXELS actually match (and whether the likeness is
    *good*) is the perceptual gate and the human tier respectively — deliberately not claimed here."""

    name = "asset-consistency"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            assets = parse_assets(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"assets not usable: {exc}")
        refs: dict[str, set[str]] = {}  # entity (normalized) -> the distinct references it was drawn with
        names: dict[str, str] = {}  # normalized -> name as written, for the message
        for im in assets.images:
            for ent, ref in im.entity_refs.items():
                refs.setdefault(_norm(ent), set()).add(ref)
                names.setdefault(_norm(ent), ent)
        drifted = {ent: sorted(rs) for ent, rs in refs.items() if len(rs) > 1}
        if drifted:
            shown = "; ".join(f"{names[ent]} requested as {' vs '.join(rs)}" for ent, rs in drifted.items())
            return self._result(False, f"inconsistent entit{'y' if len(drifted) == 1 else 'ies'}: {shown}")
        return self._result(
            True,
            f"all {len(refs)} recurring entit{'y' if len(refs) == 1 else 'ies'} requested with a stable "
            f"reference (pixel match = the perceptual gate, a later rung)",
        )


class ClipIntegrityGate(Gate):
    """HARD: every shot that carries a generated clip points at a real, decodable video whose runtime
    matches the manifest. Additive — shots with no clip (the stills-only stub/say path) aren't
    constrained, so this gate tightens the bar exactly when real video is present and is a no-op
    otherwise. (It trusts the file via ffprobe, not the generator's word.)"""

    name = "clip-integrity"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            assets = parse_assets(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"assets not usable: {exc}")
        clips = [im for im in assets.images if im.clip]
        if not clips:
            return self._result(True, "no generated clips (stills only)")
        problems: list[str] = []
        for im in clips:
            p = Path(im.clip or "")
            try:
                probed = probe_clip(p)
            except VideoError as exc:
                problems.append(str(exc))
                continue
            if im.clip_duration is not None and abs(probed.duration - im.clip_duration) > _CLIP_DURATION_TOLERANCE:
                problems.append(f"{p.name}: is {probed.duration:.2f}s, manifest says {im.clip_duration:.2f}s")
        if problems:
            shown = "; ".join(problems[:6]) + (" …" if len(problems) > 6 else "")
            return self._result(False, shown)
        return self._result(True, f"all {len(clips)} generated clip(s) decode and match the manifest")


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
