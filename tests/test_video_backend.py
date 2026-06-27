"""The video seam, offline. The real LTX backend needs a GPU + model download, so it's verified by
its argv (pure) and availability check; the actual clip rendering is proven with ScriptedVideoBackend
(a real ffmpeg clip) so the integrity path — generate → probe a decodable video — is exercised without
torch. seed_for is the consistency-by-construction primitive and must be deterministic.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from orgs.production_studio.video import (
    LocalLtxBackend,
    ScriptedVideoBackend,
    VideoError,
    probe_clip,
    seed_for,
)

has_ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def test_seed_for_is_deterministic_and_set_stable() -> None:
    a = seed_for(["Alice", "Bob"])
    assert a == seed_for(["bob", "alice"])  # order- and case-insensitive (same shot = same seed)
    assert seed_for(["Alice"]) != seed_for(["Bob"])  # different casts → different seeds
    assert seed_for([]) == 0


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg/ffprobe")
def test_scripted_backend_renders_a_real_decodable_clip(tmp_path: Path) -> None:
    out = tmp_path / "clip.mp4"
    clip = ScriptedVideoBackend().generate_clip(
        "a quiet street", out, seconds=2.0, fps=24, width=320, height=192, seed=seed_for(["Alice"]),
    )
    assert out.exists()
    assert (clip.width, clip.height) == (320, 192)
    assert clip.duration == pytest.approx(2.0, abs=0.3)
    # probing it independently agrees — we trust the file, not the backend's return
    assert probe_clip(out).width == 320


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg/ffprobe")
def test_same_seed_renders_byte_identical(tmp_path: Path) -> None:
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    backend = ScriptedVideoBackend()
    s = seed_for(["Hero"])
    backend.generate_clip("x", a, seconds=1.0, fps=24, width=128, height=128, seed=s)
    backend.generate_clip("x", b, seconds=1.0, fps=24, width=128, height=128, seed=s)
    assert a.read_bytes() == b.read_bytes()  # a recurring entity-set is visually stable


@pytest.mark.skipif(not has_ffmpeg, reason="needs ffmpeg/ffprobe")
def test_probe_rejects_a_non_video(tmp_path: Path) -> None:
    junk = tmp_path / "nope.mp4"
    junk.write_bytes(b"not a video")
    with pytest.raises(VideoError):
        probe_clip(junk)


def test_local_ltx_argv_is_correct() -> None:
    backend = LocalLtxBackend("/path/to/py312", runner=Path("/repo/scripts/ltx_runner.py"))
    argv = backend.build_argv(
        "neon city", Path("/out/clip.mp4"),
        seconds=4.0, fps=24, width=768, height=512, reference_image=None, seed=123,
    )
    assert argv[0] == "/path/to/py312"
    assert argv[1] == "/repo/scripts/ltx_runner.py"
    assert "--prompt" in argv and "neon city" in argv
    assert argv[argv.index("--out") + 1] == "/out/clip.mp4"
    assert argv[argv.index("--seed") + 1] == "123"
    assert "--image" not in argv  # omitted when no reference


def test_local_ltx_argv_includes_reference_for_i2v() -> None:
    backend = LocalLtxBackend("/py", runner=Path("/r.py"))
    argv = backend.build_argv(
        "p", Path("/o.mp4"), seconds=4.0, fps=24, width=768, height=512,
        reference_image=Path("/ref/alice.png"), seed=None,
    )
    assert argv[argv.index("--image") + 1] == "/ref/alice.png"
    assert "--seed" not in argv  # omitted when None


def test_local_ltx_unavailable_when_paths_missing(tmp_path: Path) -> None:
    backend = LocalLtxBackend(str(tmp_path / "missing_python"), runner=tmp_path / "missing_runner.py")
    assert backend.available() is False


def test_from_env_returns_none_without_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERITAS_LTX_PYTHON", raising=False)
    assert LocalLtxBackend.from_env() is None
