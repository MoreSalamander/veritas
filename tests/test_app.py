"""P9 + P10 — a plan becomes modules that coexist, then a runnable app (e2e green)."""

from __future__ import annotations

import json

from engine.artifact import Artifact, Provenance
from engine.memory import MemoryStore
from engine.model import ScriptedProvider, SequencedProvider
from orgs.software_studio.app import AssemblyGate, build_app


def _pkg(code: str) -> Artifact:
    return Artifact(type="package", owner="assembler", payload=code,
                    provenance=Provenance(created_by="assembler", rationale="test"))


def test_assembly_detects_name_clash():
    code = "def save(x):\n    return x\n\ndef save(y):\n    return y\n"
    result = AssemblyGate().check(_pkg(code))
    assert not result.passed and "save" in result.evidence


def test_assembly_passes_distinct_functions():
    code = "def save(x):\n    return x\n\ndef load(y):\n    return y\n"
    assert AssemblyGate().check(_pkg(code)).passed


# --- full build_app: plan -> modules -> package -> entrypoint -> e2e ---

PLAN = json.dumps({"app_name": "store", "modules": [
    {"module_name": "storage", "goal": "save and load a value"},
    {"module_name": "ops", "goal": "add and confirm"},
]})
C_STORAGE = json.dumps({"module_name": "storage", "functions": [
    {"function_name": "save", "signature": "def save(x)", "cases": [{"args": [5], "expected": 5}]},
    {"function_name": "load", "signature": "def load(x)", "cases": [{"args": [5], "expected": 5}]},
]})
C_OPS = json.dumps({"module_name": "ops", "functions": [
    {"function_name": "add", "signature": "def add(a, b)", "cases": [{"args": [1, 1], "expected": 2}]},
    {"function_name": "confirm", "signature": "def confirm(x)", "cases": [{"args": [1], "expected": True}]},
]})
PM_STORAGE = json.dumps(["assert load(save(7)) == 7"])
PM_OPS = json.dumps(["assert confirm(add(1, 1)) == True"])
CODE_STORAGE = "def save(x):\n    return x\n\ndef load(x):\n    return x\n"
CODE_OPS = "def add(a, b):\n    return a + b\n\ndef confirm(x):\n    return True\n"
ENTRYPOINT = "def main(x):\n    return confirm(add(load(save(x)), 1))\n"
E2E = json.dumps(["assert main(1) == True"])


def _seq(**overrides) -> SequencedProvider:
    base = {
        "planner": [PLAN],
        "architect": [C_STORAGE, C_OPS],
        "pm": [PM_STORAGE, PM_OPS, E2E],  # two module integrations, then the app e2e
        "developer": [CODE_STORAGE, CODE_OPS],
        "integrator": [ENTRYPOINT],
    }
    base.update(overrides)
    return SequencedProvider(base)


def test_build_app_produces_a_runnable_app(tmp_path):
    result = build_app("a tiny store app", _seq(), MemoryStore(tmp_path))
    assert result.accepted
    assert all(m.accepted for m in result.module_results)
    assert result.package_outcome is not None and result.package_outcome.accepted
    assert result.entrypoint_outcome is not None and result.entrypoint_outcome.accepted
    assert result.e2e_outcome is not None and result.e2e_outcome.accepted
    gate_names = [g.gate_name for g in result.e2e_outcome.artifact.provenance.gate_results]
    assert gate_names == ["e2e-spec", "e2e", "validation"]


def test_entrypoint_without_main_rejected(tmp_path):
    result = build_app("x", _seq(integrator=["def helper():\n    return 1\n"]), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.entrypoint_outcome is not None and not result.entrypoint_outcome.accepted
    assert result.e2e_outcome is None  # never reached


def test_e2e_failure_rejects_the_app(tmp_path):
    result = build_app("x", _seq(pm=[PM_STORAGE, PM_OPS, json.dumps(["assert main(1) == False"])]),
                       MemoryStore(tmp_path))
    assert not result.accepted
    assert result.e2e_outcome is not None and not result.e2e_outcome.accepted
    e2e = next(g for g in result.e2e_outcome.artifact.provenance.gate_results if g.gate_name == "e2e")
    assert not e2e.passed


def test_build_app_fails_if_a_module_fails(tmp_path):
    # The first module's developer is wrong on every retry, so the module (and the app) fails.
    bad = "def save(x):\n    return x\n\ndef load(x):\n    return 999\n"
    result = build_app("x", _seq(developer=[bad, bad, bad]), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.package_outcome is None


def test_build_app_rejects_bad_plan(tmp_path):
    result = build_app("x", ScriptedProvider({"planner": "just prose"}), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.module_results == []
