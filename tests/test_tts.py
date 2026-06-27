"""The narration seam, offline. Kokoro needs a model download + the 3.12 runtime, so it's verified by
its argv (pure) + availability/env logic; real synthesis is exercised with SilentTTSBackend (and `say`
where present) so the generator's audio path runs without a neural TTS. Quality is a listen test, not a
unit test — these prove the wiring, the manifest durations, and the backend selection.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orgs.production_studio.media import read_wav_duration
from orgs.production_studio.assets import StubGenerator
from orgs.production_studio.production import parse_script, parse_storyboard
from orgs.production_studio.tts import KokoroBackend, SayBackend, SilentTTSBackend

has_say = shutil.which("say") is not None

SCRIPT = json.dumps({"scenes": [{"heading": "A", "beats": [
    {"narration": "A quiet town wakes up slowly in the morning light.", "entities": ["town"]}]}]})
STORYBOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "the town", "entities": ["town"]}]})


def test_silent_backend_sizes_to_text(tmp_path: Path) -> None:
    out = tmp_path / "a.wav"
    d = SilentTTSBackend(words_per_second=2.0).synth("one two three four", out)  # 4 words / 2 = 2.0s
    assert d == pytest.approx(2.0, abs=0.1)
    assert read_wav_duration(out) == pytest.approx(2.0, abs=0.1)


def test_silent_backend_has_a_floor(tmp_path: Path) -> None:
    assert SilentTTSBackend().synth("", tmp_path / "e.wav") >= 0.5


def test_kokoro_argv_is_correct() -> None:
    b = KokoroBackend("/py", runner=Path("/r.py"), voice="bm_george", speed=1.1)
    argv = b.build_argv("hello world", Path("/o.wav"), None)
    assert argv[0] == "/py" and argv[1] == "/r.py"
    assert argv[argv.index("--text") + 1] == "hello world"
    assert argv[argv.index("--out") + 1] == "/o.wav"
    assert argv[argv.index("--voice") + 1] == "bm_george"
    assert argv[argv.index("--speed") + 1] == "1.1"


def test_kokoro_voice_can_be_overridden_per_call() -> None:
    argv = KokoroBackend("/py", voice="bm_george").build_argv("x", Path("/o.wav"), "af_heart")
    assert argv[argv.index("--voice") + 1] == "af_heart"  # per-line voice wins over the default


def test_kokoro_unavailable_when_paths_missing(tmp_path: Path) -> None:
    assert KokoroBackend(str(tmp_path / "nope"), runner=tmp_path / "nope.py").available() is False


def test_kokoro_from_env_none_without_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERITAS_TTS_PYTHON", raising=False)
    monkeypatch.delenv("VERITAS_LTX_PYTHON", raising=False)
    assert KokoroBackend.from_env() is None


def test_kokoro_from_env_falls_back_to_ltx_python(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    py = tmp_path / "py"
    py.write_text("")  # exists, so available() passes (the real runner ships in the repo)
    monkeypatch.delenv("VERITAS_TTS_PYTHON", raising=False)
    monkeypatch.setenv("VERITAS_LTX_PYTHON", str(py))
    b = KokoroBackend.from_env()
    assert b is not None and b.python_exe == str(py)


def test_generator_delegates_audio_to_its_tts_backend(tmp_path: Path) -> None:
    script, board = parse_script(SCRIPT), parse_storyboard(STORYBOARD)
    manifest = json.loads(StubGenerator(32, 32, tts=SilentTTSBackend(words_per_second=3.0))
                          .generate(script, board, tmp_path))
    assert all(a["duration"] > 0 for a in manifest["audio"])


@pytest.mark.skipif(not has_say, reason="needs macOS `say`")
def test_say_backend_produces_real_audio(tmp_path: Path) -> None:
    out = tmp_path / "s.wav"
    d = SayBackend().synth("Hello there, this is a narration test.", out)
    assert d > 0 and read_wav_duration(out) > 0
