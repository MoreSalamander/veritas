"""The narration seam — a backend turns a line of text into a real WAV on disk.

Mirrors the video seam exactly. `KokoroBackend` shells out to a 3.12 interpreter running
`scripts/kokoro_runner.py` (high-quality local neural TTS); Veritas's 3.14 process never imports
kokoro/torch. `SayBackend` is the macOS `say` baseline. `SilentTTSBackend` is the offline/stub default
(a real, silent WAV sized to the text). A cloud backend (e.g. ElevenLabs) implements the same interface
— local↔cloud is a config swap.

A backend returns the clip's measured duration (read back off disk for `say`/Kokoro), which the manifest
records so the timeline stays in sync — the gate trusts the file, not the synthesizer.
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from orgs.production_studio.media import read_wav_duration, write_wav
from orgs.production_studio.production import WORDS_PER_SECOND

DEFAULT_KOKORO_RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "kokoro_runner.py"
DEFAULT_KOKORO_VOICE = "af_heart"  # Kokoro's flagship voice; a*=American, b*=British language pack


class TTSError(RuntimeError):
    """Narration could not be synthesized."""


class TTSBackend(ABC):
    @abstractmethod
    def synth(self, text: str, out_path: Path, voice: str | None = None) -> float:
        """Write a real WAV of `text` to `out_path`; return its measured duration in seconds."""
        raise NotImplementedError


class SilentTTSBackend(TTSBackend):
    """A real, silent WAV sized to the text's estimated runtime — the dependency-free default."""

    def __init__(self, words_per_second: float = WORDS_PER_SECOND) -> None:
        self.wps = words_per_second

    def synth(self, text: str, out_path: Path, voice: str | None = None) -> float:
        seconds = max(0.5, len(text.split()) / self.wps)
        write_wav(out_path, seconds)
        return round(seconds, 3)


class SayBackend(TTSBackend):
    """macOS `say` — always available on a Mac, robotic. The baseline, not the quality tier."""

    def __init__(self, voice: str | None = None) -> None:
        self.voice = voice

    def synth(self, text: str, out_path: Path, voice: str | None = None) -> float:
        v = voice or self.voice
        argv = ["say", "-o", str(out_path), "--data-format=LEI16@22050"]
        if v:
            argv += ["-v", v]
        argv.append(text.strip() or " ")
        subprocess.run(argv, check=True, capture_output=True, timeout=120)
        return round(read_wav_duration(out_path), 3)


class KokoroBackend(TTSBackend):
    """High-quality local neural TTS (Kokoro), run via subprocess in a 3.12 venv. Veritas never imports
    kokoro — the subprocess boundary is the point. Verify availability before use."""

    def __init__(
        self,
        python_exe: str,
        runner: Path = DEFAULT_KOKORO_RUNNER,
        voice: str = DEFAULT_KOKORO_VOICE,
        speed: float = 1.0,
        timeout: float = 300.0,
    ) -> None:
        self.python_exe = python_exe
        self.runner = runner
        self.voice = voice
        self.speed = speed
        self.timeout = timeout

    @classmethod
    def from_env(cls, **kwargs: Any) -> KokoroBackend | None:
        """Build from VERITAS_TTS_PYTHON, falling back to VERITAS_LTX_PYTHON (the LTX venv also has
        kokoro). None if neither is set or the runtime isn't usable."""
        py = os.environ.get("VERITAS_TTS_PYTHON") or os.environ.get("VERITAS_LTX_PYTHON", "")
        if not py:
            return None
        backend = cls(py, **kwargs)
        return backend if backend.available() else None

    def available(self) -> bool:
        return Path(self.python_exe).exists() and self.runner.exists()

    def build_argv(self, text: str, out_path: Path, voice: str | None) -> list[str]:
        return [
            self.python_exe, str(self.runner),
            "--text", text.strip() or " ",
            "--out", str(out_path),
            "--voice", voice or self.voice,
            "--speed", str(self.speed),
        ]

    def synth(self, text: str, out_path: Path, voice: str | None = None) -> float:
        proc = subprocess.run(
            self.build_argv(text, out_path, voice), capture_output=True, text=True, timeout=self.timeout)
        if proc.returncode != 0:
            raise TTSError(f"kokoro failed: {proc.stderr.strip()[-300:]}")
        return round(read_wav_duration(out_path), 3)  # trust the file, not the synthesizer
