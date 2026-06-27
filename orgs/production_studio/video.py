"""The video-generation seam — a backend turns a prompt (and optionally a pinned reference image)
into a real, short video clip on disk.

Veritas runs Python 3.14, which can't install torch, so the local model can't live in-process. The
seam follows the same discipline the asset stage already uses for `say` and ffmpeg: a SUBPROCESS
boundary. `LocalLtxBackend` shells out to a 3.12 interpreter running `scripts/ltx_runner.py` (LTX-Video
on MPS); Veritas's own process never imports torch. `ScriptedVideoBackend` is the offline stand-in
(a real ffmpeg-rendered placeholder clip) so the seam is testable without a GPU or model download.

A clip is verified the same way the publish stage trusts its output: read the FILE back with ffprobe,
not the renderer's word. Whether the motion is *good* is the human tier — this seam only guarantees a
real, decodable clip of the requested shape exists.

Cloud backends (the Pro-account ZeroGPU Space, or a pay-per-clip API) implement the same interface;
local↔cloud is a config swap, exactly the local-dev / cloud-product split the engine is built around.
"""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orgs.production_studio.production import _norm

# The runner lives at the repo root: orgs/production_studio/video.py -> parents[2] == repo root.
DEFAULT_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "ltx_runner.py"
# LTX-Video 0.9.x distilled — the variant that actually fits a 24 GB M-series machine.
DEFAULT_MODEL = "Lightricks/LTX-Video"


class VideoError(RuntimeError):
    """A clip could not be generated or wasn't a decodable video."""


@dataclass
class ClipResult:
    """A generated clip, described by what ffprobe read back off disk — not what we asked for."""

    path: str
    duration: float
    width: int
    height: int
    frames: int


def seed_for(entities: list[str]) -> int:
    """A deterministic seed from the entities in a shot, so the SAME set of characters renders the
    SAME way every time it appears — visual identity pinned by construction at the seed level. (This
    is the honest Rung-1 consistency claim: 'the same reference was requested', verified by the
    metadata gate. Proving the resulting *pixels* match is the perceptual gate, a later rung.)"""
    if not entities:
        return 0
    key = "|".join(sorted(_norm(e) for e in entities))
    # A stable, reproducible int (hashlib, not the salted built-in hash()); kept in a sane range.
    import hashlib

    return int.from_bytes(hashlib.md5(key.encode()).digest()[:4], "big")


def probe_clip(path: Path) -> ClipResult:
    """ffprobe a clip → ClipResult. Raises VideoError if it isn't a decodable video file."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise VideoError(f"ffprobe could not read {path.name}: {proc.stderr.strip()[-200:]}")
    info: dict[str, Any] = json.loads(proc.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise VideoError(f"{path.name} has no video stream")
    try:
        width = int(video["width"])
        height = int(video["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise VideoError(f"{path.name}: unreadable dimensions ({exc})") from exc
    try:
        duration = float(info.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    nb = video.get("nb_frames")
    try:
        frames = int(nb) if nb not in (None, "N/A") else 0
    except (TypeError, ValueError):
        frames = 0
    return ClipResult(str(path), round(duration, 3), width, height, frames)


class VideoBackend(ABC):
    """Produces ONE clip per call. `reference_image`, when given, conditions the clip on a pinned
    still (image-to-video) — the mechanism for keeping an entity's look stable across shots."""

    @abstractmethod
    def generate_clip(
        self,
        prompt: str,
        out_path: Path,
        *,
        seconds: float,
        fps: int,
        width: int,
        height: int,
        reference_image: Path | None = None,
        seed: int | None = None,
    ) -> ClipResult:
        raise NotImplementedError


def _run(cmd: list[str], timeout: float) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise VideoError(f"{Path(cmd[0]).name} failed: {proc.stderr.strip()[-400:]}")


class ScriptedVideoBackend(VideoBackend):
    """Offline stand-in: a real, ffprobe-valid clip rendered by ffmpeg (a solid color seeded so the
    same shot is byte-stable). No GPU, no model download — proves the seam and the integrity gate."""

    def generate_clip(
        self,
        prompt: str,
        out_path: Path,
        *,
        seconds: float,
        fps: int,
        width: int,
        height: int,
        reference_image: Path | None = None,
        seed: int | None = None,
    ) -> ClipResult:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # A deterministic color from the seed → recurring entity-sets render identically here too.
        c = (seed if seed is not None else 0) & 0xFFFFFF
        color = f"0x{c:06X}"
        _run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"color=c={color}:s={width}x{height}:d={seconds}:r={fps}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)],
            timeout=120,
        )
        return probe_clip(out_path)


class LocalLtxBackend(VideoBackend):
    """The real local engine: shells out to a 3.12 interpreter running the LTX runner on MPS. Veritas
    never imports torch — the subprocess boundary is the whole point. Verify availability before use."""

    def __init__(
        self,
        python_exe: str,
        runner: Path = DEFAULT_RUNNER,
        model_id: str = DEFAULT_MODEL,
        steps: int = 25,
        guidance: float = 3.0,
        timeout: float = 1800.0,
    ) -> None:
        # Defaults target the 2B BASE checkpoint (the one that fits 24 GB): ~25 steps + CFG ~3.0.
        # A distilled checkpoint would instead want steps 4-10 + guidance 1.0.
        self.python_exe = python_exe
        self.runner = runner
        self.model_id = model_id
        self.steps = steps
        self.guidance = guidance
        self.timeout = timeout

    @classmethod
    def from_env(cls, **kwargs: Any) -> LocalLtxBackend | None:
        """Build from VERITAS_LTX_PYTHON (a 3.12 venv with diffusers+torch). None if unset/unusable."""
        import os

        py = os.environ.get("VERITAS_LTX_PYTHON", "")
        if not py:
            return None
        backend = cls(py, **kwargs)
        return backend if backend.available() else None

    def available(self) -> bool:
        return Path(self.python_exe).exists() and self.runner.exists()

    def build_argv(
        self,
        prompt: str,
        out_path: Path,
        *,
        seconds: float,
        fps: int,
        width: int,
        height: int,
        reference_image: Path | None,
        seed: int | None,
    ) -> list[str]:
        argv = [
            self.python_exe, str(self.runner),
            "--prompt", prompt,
            "--out", str(out_path),
            "--seconds", str(seconds),
            "--fps", str(fps),
            "--width", str(width),
            "--height", str(height),
            "--model", self.model_id,
            "--steps", str(self.steps),
            "--guidance", str(self.guidance),
        ]
        if reference_image is not None:
            argv += ["--image", str(reference_image)]
        if seed is not None:
            argv += ["--seed", str(seed)]
        return argv

    def generate_clip(
        self,
        prompt: str,
        out_path: Path,
        *,
        seconds: float,
        fps: int,
        width: int,
        height: int,
        reference_image: Path | None = None,
        seed: int | None = None,
    ) -> ClipResult:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        argv = self.build_argv(
            prompt, out_path, seconds=seconds, fps=fps, width=width, height=height,
            reference_image=reference_image, seed=seed,
        )
        _run(argv, timeout=self.timeout)
        return probe_clip(out_path)  # trust the file, not the runner
