"""P6 definition-of-done — the org builds a small MODULE, with Architect + PM gated.

The heart of P6 is the composition boundary: each function can pass its own cases yet
fail when composed. The integration gate is what catches that — and it's the test that
proves the new boundary is real, not the happy path.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.software_studio.module import build_module

CONTRACT = json.dumps(
    {
        "module_name": "temperature",
        "functions": [
            {
                "function_name": "celsius_to_fahrenheit",
                "signature": "def celsius_to_fahrenheit(c)",
                "cases": [{"args": [0], "expected": 32}, {"args": [100], "expected": 212}],
            },
            {
                "function_name": "fahrenheit_to_celsius",
                "signature": "def fahrenheit_to_celsius(f)",
                "cases": [{"args": [32], "expected": 0}],
            },
        ],
    }
)
PM_TESTS = json.dumps(
    [
        "assert abs(fahrenheit_to_celsius(celsius_to_fahrenheit(100)) - 100) < 1e-9",
        "assert celsius_to_fahrenheit(0) == 32",
    ]
)
GOOD_MODULE = (
    "def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32\n\n"
    "def fahrenheit_to_celsius(f):\n    return (f - 32) * 5 / 9\n"
)
# Each function passes its OWN cases (ftc only tests 32->0), but composed it's wrong.
COMPOSES_WRONG_MODULE = (
    "def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32\n\n"
    "def fahrenheit_to_celsius(f):\n    return 0\n"
)


def _provider(contract: str, pm: str, code: str) -> ScriptedProvider:
    return ScriptedProvider({"architect": contract, "pm": pm, "developer": code})


def test_clean_module_ships_with_full_provenance(tmp_path):
    result = build_module("temperature conversion", _provider(CONTRACT, PM_TESTS, GOOD_MODULE),
                          MemoryStore(tmp_path))
    assert result.accepted
    assert result.contract_outcome.artifact.type == "contract"
    assert result.integration_outcome is not None
    assert result.integration_outcome.artifact.type == "integration-spec"
    assert result.code_outcome is not None and result.code_outcome.accepted
    gate_names = [g.gate_name for g in result.code_outcome.artifact.provenance.gate_results]
    assert gate_names == ["module-syntax", "acceptance-tests", "security-scan", "integration", "validation"]


def test_integration_gate_catches_composition_failure(tmp_path):
    # THE P6 POINT: per-function cases all pass, but the parts fail composed.
    result = build_module("temperature", _provider(CONTRACT, PM_TESTS, COMPOSES_WRONG_MODULE),
                          MemoryStore(tmp_path))
    assert not result.accepted
    assert result.code_outcome is not None
    gates = {g.gate_name: g for g in result.code_outcome.artifact.provenance.gate_results}
    assert gates["acceptance-tests"].passed  # each function passed its own cases
    assert not gates["integration"].passed  # but they don't compose
    assert result.code_outcome.memory_path.parent.name == "failures"


def test_contract_needs_at_least_two_functions(tmp_path):
    one_fn = json.dumps(
        {"module_name": "x", "functions": [
            {"function_name": "f", "signature": "def f(a)", "cases": [{"args": [1], "expected": 1}]}]}
    )
    result = build_module("x", _provider(one_fn, PM_TESTS, GOOD_MODULE), MemoryStore(tmp_path))
    assert not result.accepted
    assert not result.contract_outcome.accepted
    assert result.integration_outcome is None  # PM never ran


def test_integration_spec_must_touch_two_functions(tmp_path):
    weak_pm = json.dumps(["assert celsius_to_fahrenheit(0) == 32"])  # only one function
    result = build_module("x", _provider(CONTRACT, weak_pm, GOOD_MODULE), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.integration_outcome is not None and not result.integration_outcome.accepted
    assert result.code_outcome is None  # developer never ran


def test_missing_function_rejected_by_module_syntax(tmp_path):
    half = "def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32\n"  # ftc missing
    result = build_module("x", _provider(CONTRACT, PM_TESTS, half), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.code_outcome is not None
    syntax = next(g for g in result.code_outcome.artifact.provenance.gate_results if g.gate_name == "module-syntax")
    assert not syntax.passed
