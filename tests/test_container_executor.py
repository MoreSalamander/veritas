"""P31a — the sandboxed Executor, verified live against Docker (skipped if the daemon isn't up).

Two things must hold: (1) the container is genuinely ISOLATED — no network, read-only root, memory cap
kills a bomb — so a stranger's model-generated code can't harm the host; and (2) the VERDICTS are
UNCHANGED — a gate run through the sandbox reaches the same accept/reject as the local executor. The
sandbox contains; it must never change what the gates decide.
"""

from __future__ import annotations

import json

import pytest

from engine.artifact import Artifact
from engine.executor import ContainerExecutor, LocalSubprocessExecutor, default_executor
from orgs.software_studio.gates import PropertyGate
from orgs.software_studio.properties import parse_properties

pytestmark = pytest.mark.skipif(not ContainerExecutor.available(), reason="needs a running Docker daemon")


def _art(code: str) -> Artifact:
    return Artifact.propose(type="code", owner="t", payload=code, rationale="t")


# --- it runs real code, same answer as local --------------------------------------------------

def test_container_runs_code_and_matches_local():
    code = "print(sum(range(100)))"
    assert ContainerExecutor().run(code, {}, 15).stdout.strip() == "4950"
    assert LocalSubprocessExecutor().run(code, {}, 15).stdout.strip() == "4950"


def test_env_additions_reach_the_container():
    code = "import os; print(os.environ['VERITAS_X'])"
    assert ContainerExecutor().run(code, {"VERITAS_X": "hello"}, 15).stdout.strip() == "hello"


# --- it is genuinely isolated -----------------------------------------------------------------

def test_network_is_blocked():
    code = "import socket; socket.create_connection(('1.1.1.1', 80), timeout=4); print('CONNECTED')"
    res = ContainerExecutor().run(code, {}, 20)
    assert not res.ok and "CONNECTED" not in res.stdout  # --network none


def test_root_filesystem_is_read_only_but_tmp_works():
    res = ContainerExecutor().run("open('/etc/evil', 'w').write('x'); print('WROTE')", {}, 15)
    assert not res.ok and "WROTE" not in res.stdout                       # read-only root
    ok = ContainerExecutor().run("open('/tmp/x','w').write('ok'); print(open('/tmp/x').read())", {}, 15)
    assert ok.stdout.strip() == "ok"                                       # tmpfs scratch is writable


def test_memory_bomb_is_killed():
    res = ContainerExecutor(memory="256m").run("x = bytearray(600 * 1024 * 1024); print('ALLOCATED')", {}, 25)
    assert not res.ok and "ALLOCATED" not in res.stdout                    # OOM-killed under the cap


def test_run_argv_injects_files_and_runs():
    res = ContainerExecutor().run_argv(["python", "main.py"], {}, 20, files={"main.py": "print('argv ok')"})
    assert res.ok and "argv ok" in res.stdout


# --- THE INVARIANT: isolation does not change the verdict --------------------------------------

_PROPS = parse_properties(json.loads(
    '[{"kind": "invariant", "invariant": "is_permutation_of_input", "inputs": [[[3, 1, 2]]]}]'))
_WRONG = "def f(xs):\n    return sorted(xs)[1:]\n"   # drops an element
_RIGHT = "def f(xs):\n    return sorted(xs)\n"


def test_gate_verdict_is_identical_local_vs_sandboxed():
    for code, expected in [(_WRONG, False), (_RIGHT, True)]:
        local = PropertyGate("f", _PROPS, executor=LocalSubprocessExecutor()).check(_art(code))
        cont = PropertyGate("f", _PROPS, executor=ContainerExecutor()).check(_art(code))
        assert local.passed == cont.passed == expected  # contained, but the verdict is unchanged


def test_the_sandbox_is_the_default_and_local_is_the_opt_out(monkeypatch):
    """Isolation unless told otherwise, and the escape hatch still works.

    This assertion used to run the other way round — unset meant a local
    subprocess, and a container was the thing you had to ask for. Two problems
    with that default pointed the same way: what runs here is model-generated
    code, so isolating it by default is the right way round; and the wedge fails
    closed without isolation, so a machine that had never set the variable
    reported the headline feature offline. Someone who had just cloned the repo
    could not tell that from broken.
    """
    monkeypatch.delenv("VERITAS_SANDBOX", raising=False)
    assert isinstance(default_executor(), ContainerExecutor)
    monkeypatch.setenv("VERITAS_SANDBOX", "container")
    assert isinstance(default_executor(), ContainerExecutor)
    # Deliberately opting out is still possible, and is now the explicit act.
    monkeypatch.setenv("VERITAS_SANDBOX", "local")
    assert isinstance(default_executor(), LocalSubprocessExecutor)
