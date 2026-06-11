"""P12 — the retry loop: on rejection, re-propose with gate feedback within the run.

Proven offline: a developer that fails its first attempt and corrects itself once it sees
the failing-gate evidence yields an accepted build (the org fixes its own work instead of
dying). Exhausting the attempts returns the best one and stays rejected — the retry never
weakens the gates to force a pass. Works at the module level too.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ModelProvider, ScriptedProvider
from orgs.software_studio.module import build_module
from orgs.software_studio.pipeline import build_software

SPEC = json.dumps(
    {"function_name": "add", "description": "add", "signature": "def add(a, b)",
     "cases": [{"args": [1, 2], "expected": 3}, {"args": [5, 5], "expected": 10}],
     # Oracle-free: as the second arg climbs, the sum must climb. a-b breaks this — so the
     # HARD property gate (not a model-authored case) is what triggers the retry.
     "properties": [{"kind": "monotonic", "direction": "increasing",
                     "inputs": [[0, 1], [0, 2], [0, 3]]}]}
)
GOOD_CODE = "def add(a, b):\n    return a + b\n"
WRONG_CODE = "def add(a, b):\n    return a - b\n"  # passes syntax, fails the monotonic property


class _SelfCorrectingDev(ModelProvider):
    """Returns wrong code first; once it sees the rejection feedback, returns correct code."""

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        if role == "spec":
            return SPEC
        if role == "qa":
            return "[]"
        if role == "developer":
            return GOOD_CODE if "previously" in prompt.lower() or "rejected" in prompt.lower() else WRONG_CODE
        raise KeyError(role)


def test_developer_retries_to_a_pass(tmp_path):
    result = build_software("add two numbers", _SelfCorrectingDev(), MemoryStore(tmp_path))
    assert result.accepted  # failed attempt 1, fixed itself on attempt 2
    assert any(e.actor == "retry" for e in result.activity)
    assert result.code_outcome is not None and result.code_outcome.artifact.payload == GOOD_CODE


def test_retry_exhausts_and_stays_rejected(tmp_path):
    # Always-wrong developer: retries, never passes, returns the best (still rejected) attempt.
    provider = ScriptedProvider({"spec": SPEC, "developer": WRONG_CODE, "qa": "[]"})
    result = build_software("add", provider, MemoryStore(tmp_path))
    assert not result.accepted
    assert len([e for e in result.activity if e.actor == "retry"]) >= 1


MOD_CONTRACT = json.dumps(
    {"module_name": "m", "functions": [
        {"function_name": "inc", "signature": "def inc(x)", "cases": [{"args": [1], "expected": 2}]},
        {"function_name": "dec", "signature": "def dec(x)", "cases": [{"args": [1], "expected": 0}]}]}
)
MOD_PM = json.dumps(["assert dec(inc(5)) == 5"])
MOD_GOOD = "def inc(x):\n    return x + 1\n\ndef dec(x):\n    return x - 1\n"
MOD_WRONG = "def inc(x):\n    return x + 1\n\ndef dec(x):\n    return x - 2\n"  # dec wrong


class _SelfCorrectingModuleDev(ModelProvider):
    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        if role == "architect":
            return MOD_CONTRACT
        if role == "pm":
            return MOD_PM
        if role == "developer":
            return MOD_GOOD if "rejected" in prompt.lower() else MOD_WRONG
        raise KeyError(role)


def test_module_developer_retries_to_a_pass(tmp_path):
    result = build_module("a counter module", _SelfCorrectingModuleDev(), MemoryStore(tmp_path))
    assert result.accepted
    assert any(e.actor == "retry" for e in result.activity)
