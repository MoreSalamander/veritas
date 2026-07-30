"""orgs/hunter_engine_bridge.py's containerized invocation path — the first
proof that an engine can run as a genuinely disposable Docker container
spawned by Veritas, using the same host-socket mechanism verified in
deploy/local/, with zero changes to the bridge's existing stdout-parsing or
DataHub-reading contract (only how `proc` gets produced changes).

Two tiers: fast unit tests (mocked, no Docker needed) confirm the argv build
and the pause pre-flight; a slower, Docker-gated integration test (skipped
like tests/test_container_executor.py when no daemon is up) builds the real
crypto-hunter image and proves a datahub.sqlite3 write survives --rm.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.executor import ContainerExecutor
from engine.memory import MemoryStore
from orgs.hunter_engine_bridge import _is_paused, _run_container, run_hunter_engine


# --- argv building (mocked, no Docker needed) --------------------------------------------------

def test_run_container_only_forwards_env_vars_actually_set(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    env = {"ANTHROPIC_API_KEY": "sk-test", "LLM_PROVIDER": "anthropic"}  # ETHERSCAN_API_KEY absent
    with patch.dict(os.environ, env, clear=False), patch("orgs.hunter_engine_bridge.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_container("crypto_hunter", tmp_path)

    argv = mock_run.call_args.args[0]
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "crypto-hunter-engine:local" in argv
    assert "-e" in argv and "ANTHROPIC_API_KEY" in argv and "LLM_PROVIDER" in argv
    assert "ETHERSCAN_API_KEY" not in argv  # never invent a var the caller didn't set
    assert f"{tmp_path / 'data'}:/app/data" in argv
    assert f"{tmp_path / 'config'}:/app/config" in argv


def test_run_hunter_engine_uses_container_path_when_sandbox_env_set(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory")
    fake_proc = MagicMock(returncode=0, stdout="== gate ==\n", stderr="")
    with patch.dict(os.environ, {"VERITAS_HUNTER_SANDBOX": "container"}, clear=False), \
         patch("orgs.hunter_engine_bridge.ContainerExecutor.available", return_value=True), \
         patch("orgs.hunter_engine_bridge._run_container", return_value=fake_proc) as mock_container, \
         patch("orgs.hunter_engine_bridge.subprocess.run") as mock_subprocess:
        run_hunter_engine("crypto_hunter", tmp_path, MagicMock(), memory, "run today's hunt")

    mock_container.assert_called_once_with("crypto_hunter", tmp_path)
    mock_subprocess.assert_not_called()  # the local .venv path must not also run


def test_run_hunter_engine_falls_back_to_subprocess_when_sandbox_unset(tmp_path: Path) -> None:
    """No regression for collectible_hunter/free_money_hunter, which don't get
    a Dockerfile in this pass — unset VERITAS_HUNTER_SANDBOX must behave
    exactly as before this change."""
    memory = MemoryStore(tmp_path / "memory")
    fake_proc = MagicMock(returncode=0, stdout="", stderr="")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VERITAS_HUNTER_SANDBOX", None)
        with patch("orgs.hunter_engine_bridge._run_container") as mock_container, \
             patch("orgs.hunter_engine_bridge.subprocess.run", return_value=fake_proc) as mock_subprocess:
            run_hunter_engine("crypto_hunter", tmp_path, MagicMock(), memory, "run today's hunt")

    mock_container.assert_not_called()
    mock_subprocess.assert_called_once()
    assert mock_subprocess.call_args.kwargs["cwd"] == tmp_path


# --- the pause pre-flight -----------------------------------------------------------------------

def test_is_paused_reads_the_engines_own_pause_file(tmp_path: Path) -> None:
    assert _is_paused(tmp_path) is False  # missing file fails open
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "pause.json").write_text(json.dumps({"paused": True}))
    assert _is_paused(tmp_path) is True


def test_is_paused_fails_open_on_corrupt_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "pause.json").write_text("{not json")
    assert _is_paused(tmp_path) is False


def test_run_hunter_engine_skips_container_entirely_when_paused(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "pause.json").write_text(json.dumps({"paused": True}))
    memory = MemoryStore(tmp_path / "memory")

    with patch("orgs.hunter_engine_bridge._run_container") as mock_container, \
         patch("orgs.hunter_engine_bridge.subprocess.run") as mock_subprocess:
        result = run_hunter_engine("crypto_hunter", tmp_path, MagicMock(), memory, "run today's hunt")

    mock_container.assert_not_called()
    mock_subprocess.assert_not_called()
    assert result.accepted is False
    assert result.outcomes == []
    assert "paused" in result.activity[-1].message


# --- the real thing (skipped without a live Docker daemon) -------------------------------------

_CRYPTO_HUNTER = Path.home() / "MoreSalamander" / "crypto-hunter"
_IMAGE_BUILDABLE = _CRYPTO_HUNTER.exists() and (_CRYPTO_HUNTER / "deploy" / "docker" / "Dockerfile").exists()

@pytest.mark.skipif(
    not (ContainerExecutor.available() and _IMAGE_BUILDABLE),
    reason="needs a running Docker daemon and a local crypto-hunter checkout with deploy/docker/Dockerfile",
)
def test_real_container_writes_survive_rm_via_the_bind_mount(tmp_path: Path) -> None:
    """The actual thesis: a --rm container writing to the bind-mounted /app/data
    leaves that write on the HOST path after the container is torn down — the
    exact mechanism _outcomes_from_datahub depends on. Overrides the image's
    CMD with a trivial write instead of a real `day` cycle, so this proves the
    disposable-container + volume-mount mechanism without spending real
    Anthropic/OpenAI API calls in the test suite."""
    subprocess.run(
        ["docker", "build", "-t", "crypto-hunter-engine:local",
         "-f", str(_CRYPTO_HUNTER / "deploy" / "docker" / "Dockerfile"), str(_CRYPTO_HUNTER)],
        check=True, capture_output=True, timeout=300,
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    marker_write = "import sqlite3; c = sqlite3.connect('/app/data/datahub.sqlite3'); c.execute(\"CREATE TABLE opportunities (id TEXT PRIMARY KEY, trust_status TEXT, updated_at TEXT, spec_json TEXT)\"); c.commit()"
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{data_dir}:/app/data",
         "crypto-hunter-engine:local", "python", "-c", marker_write],
        check=True, capture_output=True, timeout=60,
    )

    db_path = data_dir / "datahub.sqlite3"
    assert db_path.exists()  # survived --rm because it was bind-mounted, not baked into the container's own fs
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    assert ("opportunities",) in tables
