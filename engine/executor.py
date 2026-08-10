"""The execution boundary — where untrusted, model-generated code runs.

Our reliability comes from gates, and two of them (acceptance, qa) EXECUTE
model-generated code. On a developer's machine that's their own code on their own
hardware. Hosted, it becomes a remote-code-execution surface. So execution goes
behind this seam: a local subprocess today, a sandboxed worker (container/microVM)
tomorrow — and the gates never change. This is the seam deployment demands, the
sibling of the model boundary.
"""

from __future__ import annotations

import os
import shutil
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


class ContainerExecutor(Executor):
    """Runs untrusted, model-generated code in an EPHEMERAL, locked-down container — the hosting-grade
    replacement for LocalSubprocessExecutor. Same ExecResult contract, so the gates' VERDICTS are
    identical; only the blast radius changes. Each run is its own throwaway box with: no network
    (`--network none`), a read-only root, a small tmpfs scratch, capped memory/cpu/process-count, a
    non-root unprivileged user, all Linux capabilities dropped, no-new-privileges, and `--rm` so it
    vanishes. A malicious or runaway program can only wreck the box, which is then deleted.
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        memory: str = "256m",
        cpus: str = "1.0",
        pids: int = 128,
        tmpfs_size: str = "64m",
        user: str = "65534",  # nobody
        docker: str | None = None,
        overhead: float = 20.0,  # container-startup grace added to the inner timeout
    ) -> None:
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids = pids
        self.tmpfs_size = tmpfs_size
        self.user = user
        self.docker = docker or shutil.which("docker") or "docker"
        self.overhead = overhead

    @classmethod
    def available(cls) -> bool:
        """Docker is installed AND the daemon answers — checked before we ever rely on the sandbox."""
        d = shutil.which("docker")
        if not d:
            return False
        try:
            return subprocess.run([d, "info"], capture_output=True, timeout=20).returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _flags(self, env: dict[str, str], tmpfs: list[str]) -> list[str]:
        # forward ONLY the caller's added vars (e.g. VERITAS_CASES) — never the host's whole environment
        added = {k: v for k, v in env.items() if os.environ.get(k) != v}
        flags = [
            "run", "--rm", "-i",
            "--network", "none",
            "--read-only",
            "--memory", self.memory, "--memory-swap", self.memory,  # equal => no swap escape
            "--cpus", self.cpus,
            "--pids-limit", str(self.pids),
            "--user", self.user,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "-e", "HOME=/tmp",
        ]
        for m in tmpfs:
            flags += ["--tmpfs", m]
        for k, v in added.items():
            flags += ["-e", f"{k}={v}"]
        return flags

    def run(self, code: str, env: dict[str, str], timeout: float) -> ExecResult:
        argv = [self.docker, *self._flags(env, [f"/tmp:rw,size={self.tmpfs_size},mode=1777"]),
                self.image, "python", "-"]  # the script arrives on stdin (no arg-length / quoting issues)
        try:
            proc = subprocess.run(argv, input=code, capture_output=True, text=True,
                                  timeout=timeout + self.overhead)
        except subprocess.TimeoutExpired:
            return ExecResult(ok=False, timed_out=True, stdout="", stderr=f"timed out after {timeout}s")
        return ExecResult(ok=proc.returncode == 0, timed_out=False, stdout=proc.stdout, stderr=proc.stderr)

    def run_argv(
        self, argv: list[str], env: dict[str, str], timeout: float,
        files: dict[str, str] | None = None,
    ) -> ExecResult:
        import io
        import shlex
        import tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:  # ship files in via a tar stream (no host mount)
            for name, content in (files or {}).items():
                data = content.encode()
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
        inner = f"cd /work && tar xf - && {shlex.join(argv)}"
        dargv = [self.docker, *self._flags(
            env, [f"/tmp:rw,size={self.tmpfs_size},mode=1777",
                  f"/work:rw,size={self.tmpfs_size},mode=1777"]),
            "-w", "/work", self.image, "sh", "-c", inner]
        try:
            proc = subprocess.run(dargv, input=buf.getvalue(), capture_output=True,
                                  timeout=timeout + self.overhead)
        except subprocess.TimeoutExpired:
            return ExecResult(ok=False, timed_out=True, stdout="", stderr=f"timed out after {timeout}s")
        return ExecResult(ok=proc.returncode == 0, timed_out=False,
                          stdout=proc.stdout.decode(errors="replace"),
                          stderr=proc.stderr.decode(errors="replace"))


def default_executor() -> Executor:
    """The execution backend the whole system uses. A sandboxed container when Docker is up, else a
    local subprocess. One swap point: every gate that runs code is isolated, gates unchanged.

    Container is the DEFAULT rather than an opt-in, for two reasons that point the same way.

    It is the safer default. What runs here is model-generated code; isolating it unless told
    otherwise is the right way round, and the previous default ran it as a plain subprocess on the
    host until someone remembered an env var.

    And it is what a fresh clone needs. The wedge fails closed without isolation, so on a machine
    that had not set VERITAS_SANDBOX the headline feature reported itself offline — which is honest
    and, for someone who just cloned this to try it, indistinguishable from broken. Docker present
    means it works; Docker absent means the same local subprocess as before and the same honest
    refusal from the wedge. Set VERITAS_SANDBOX=local to force the subprocess deliberately."""
    mode = os.environ.get("VERITAS_SANDBOX", "container").lower()
    if mode in ("container", "docker") and ContainerExecutor.available():
        return ContainerExecutor()
    return LocalSubprocessExecutor()


def sandbox_active() -> bool:
    """True only when untrusted code is actually isolated in a container right now — the precondition
    the hosted wedge FAILS CLOSED on. It re-decides live (env set AND the Docker daemon answering), so
    if the sandbox was configured but the daemon is down, this reports False and a stranger's code is
    refused rather than run on the host."""
    return isinstance(default_executor(), ContainerExecutor)
