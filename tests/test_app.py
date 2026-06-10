"""P9 — Assembly: a plan becomes modules that must coexist as one package."""

from __future__ import annotations

import json

from engine.artifact import Artifact, Provenance
from engine.memory import MemoryStore
from engine.model import ScriptedProvider, SequencedProvider
from orgs.software_studio.app import AssemblyGate, build_app

# --- AssemblyGate unit checks (the new composition boundary) ---


def _pkg(code: str) -> Artifact:
    return Artifact(type="package", owner="assembler", payload=code,
                    provenance=Provenance(created_by="assembler", rationale="test"))


def test_assembly_detects_name_clash():
    code = "def save(x):\n    return x\n\ndef save(y):\n    return y\n"
    result = AssemblyGate().check(_pkg(code))
    assert not result.passed and "save" in result.evidence


def test_assembly_passes_distinct_functions():
    code = "def save(x):\n    return x\n\ndef load(y):\n    return y\n"
    result = AssemblyGate().check(_pkg(code))
    assert result.passed


# --- full build_app over two modules ---

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


def _seq() -> SequencedProvider:
    return SequencedProvider({
        "planner": [PLAN],
        "architect": [C_STORAGE, C_OPS],
        "pm": [PM_STORAGE, PM_OPS],
        "developer": [CODE_STORAGE, CODE_OPS],
    })


def test_build_app_assembles_two_modules(tmp_path):
    result = build_app("a tiny store app", _seq(), MemoryStore(tmp_path))
    assert result.accepted
    assert len(result.module_results) == 2 and all(m.accepted for m in result.module_results)
    assert result.package_outcome is not None
    assert result.package_outcome.artifact.type == "package"
    gate_names = [g.gate_name for g in result.package_outcome.artifact.provenance.gate_results]
    assert gate_names == ["assembly", "validation"]


def test_build_app_fails_if_a_module_fails(tmp_path):
    provider = SequencedProvider({
        "planner": [PLAN],
        "architect": [C_STORAGE, C_OPS],
        "pm": [PM_STORAGE, PM_OPS],
        "developer": ["def save(x):\n    return x\n\ndef load(x):\n    return 999\n", CODE_OPS],
    })
    result = build_app("x", provider, MemoryStore(tmp_path))
    assert not result.accepted
    assert result.package_outcome is None  # never assembled


def test_build_app_rejects_bad_plan(tmp_path):
    result = build_app("x", ScriptedProvider({"planner": "just prose"}), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.module_results == []
