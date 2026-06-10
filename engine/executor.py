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
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecResult:
    ok: bool  # process exited 0
    timed_out: bool
    stdout: str
    stderr: str


class Executor(ABC):
    @abstractmethod
    def run(self, code: str, env: dict[str, str], timeout: float) -> ExecResult:
        raise NotImplementedError


class LocalSubprocessExecutor(Executor):
    """Runs code in a child Python process on this machine. The floor of isolation;
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
