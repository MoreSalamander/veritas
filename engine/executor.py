"""The execution boundary — where untrusted, model-generated code runs.

Our reliability comes from gates, and two of them (acceptance, qa) EXECUTE
model-generated code. On a developer's machine that's their own code on their own
hardware. Hosted, it becomes a remote-code-execution surface. So execution goes
behind this seam: a local subprocess today, a sandboxed worker (container/microVM)
tomorrow — and the gates never change. This is the seam deployment demands, the
sibling of the model boundary.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecResult:
    ok: bool  # process exited 0
    timed_out: bool
    stdout: str
    stderr: str


class Executor(ABC):
    @abstractmethod
    def run(self, code: str, env: dict[str, str], timeout: float) -> ExecResult:
        """Run a Python code string (the original, Python-only boundary)."""
        raise NotImplementedError

    @abstractmethod
    def run_argv(
        self, argv: list[str], env: dict[str, str], timeout: float,
        files: dict[str, str] | None = None,
    ) -> ExecResult:
        """Write `files` into a scratch dir and run `argv` there. The language-agnostic
        boundary: run JS with ["node", "main.js"], a compiled language with a build+run, etc.
        The same seam a sandboxed executor will reimplement for hosting."""
        raise NotImplementedError


class LocalSubprocessExecutor(Executor):
    """Runs code in a child process on this machine. The floor of isolation;
    a sandboxed executor is a drop-in replacement for hosting."""

    def run(self, code: str, env: dict[str, str], timeout: float) -> ExecResult:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(ok=False, timed_out=True, stdout="", stderr=f"timed out after {timeout}s")
        return ExecResult(
            ok=proc.returncode == 0, timed_out=False, stdout=proc.stdout, stderr=proc.stderr
        )

    def run_argv(
        self, argv: list[str], env: dict[str, str], timeout: float,
        files: dict[str, str] | None = None,
    ) -> ExecResult:
        try:
            with tempfile.TemporaryDirectory() as scratch:
                for name, content in (files or {}).items():
                    (Path(scratch) / name).write_text(content)
                proc = subprocess.run(
                    argv, cwd=scratch, capture_output=True, text=True, timeout=timeout, env=env,
                )
        except subprocess.TimeoutExpired:
            return ExecResult(ok=False, timed_out=True, stdout="", stderr=f"timed out after {timeout}s")
        except FileNotFoundError as exc:  # the language's toolchain isn't installed
            return ExecResult(ok=False, timed_out=False, stdout="", stderr=f"toolchain missing: {exc}")
        return ExecResult(
            ok=proc.returncode == 0, timed_out=False, stdout=proc.stdout, stderr=proc.stderr
        )
