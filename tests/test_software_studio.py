"""Phase 1 definition-of-done — the first honest run.

Proven offline with a ScriptedProvider (no model running): one goal earns a real,
gate-validated function into institutional memory, and two distinct failure modes
land in failure memory — a non-executable spec (rejected before any code) and code
that fails the spec's cases. The green is earned by deterministic gates.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.software_studio.pipeline import build_function

GOOD_SPEC = json.dumps(
    {
        "function_name": "add",
        "description": "add two numbers",
        "signature": "def add(a, b)",
        "cases": [
            {"args": [1, 2], "expected": 3},
            {"args": [5, 5], "expected": 10},
            {"args": [-1, 1], "expected": 0},
        ],
    }
)
GOOD_CODE = "def add(a, b):\n    return a + b\n"
WRONG_CODE = "def add(a, b):\n    return a - b\n"
PROSE_SPEC = "Sure! You'll want a function that adds two numbers and returns the sum."


def test_good_run_earns_code_into_memory(tmp_path):
    provider = ScriptedProvider({"spec": GOOD_SPEC, "developer": GOOD_CODE})
    result = build_function("add two numbers", provider, MemoryStore(tmp_path))

    assert result.accepted
    assert result.spec_outcome.accepted
    assert result.code_outcome is not None and result.code_outcome.accepted
    assert result.code_outcome.memory_path.parent.name == "institutional"
    assert "all gates passed" in (result.code_outcome.artifact.provenance.accepted_because or "")


def test_prose_spec_rejected_before_any_code(tmp_path):
    provider = ScriptedProvider({"spec": PROSE_SPEC, "developer": GOOD_CODE})
    result = build_function("add", provider, MemoryStore(tmp_path))

    assert not result.accepted
    assert not result.spec_outcome.accepted
    assert result.code_outcome is None  # the developer never ran
    assert result.spec_outcome.memory_path.parent.name == "failures"
    assert "not executable" in result.spec_outcome.memory_path.read_text()


def test_wrong_code_rejected_by_acceptance_gate(tmp_path):
    provider = ScriptedProvider({"spec": GOOD_SPEC, "developer": WRONG_CODE})
    result = build_function("add", provider, MemoryStore(tmp_path))

    assert result.spec_outcome.accepted  # the spec was fine
    assert not result.accepted  # but the code failed the cases
    assert result.code_outcome is not None
    assert result.code_outcome.memory_path.parent.name == "failures"


def test_code_fences_are_stripped(tmp_path):
    fenced = "```python\ndef add(a, b):\n    return a + b\n```"
    provider = ScriptedProvider({"spec": GOOD_SPEC, "developer": fenced})
    result = build_function("add", provider, MemoryStore(tmp_path))
    assert result.accepted


REVERSE_SPEC = json.dumps(
    {
        "function_name": "reverse_string",
        "description": "reverse a string",
        "signature": "def reverse_string(s)",
        "cases": [
            {"args": ["hello"], "expected": "olleh"},
            {"args": ["abc"], "expected": "cba"},
            {"args": ["a'b"], "expected": "b'a"},  # embedded quote — the exact bug
        ],
    }
)


def test_string_args_with_quotes_do_not_break_the_harness(tmp_path):
    # Regression: the first real LLM run rejected CORRECT code because case values
    # were interpolated into harness source and a quote collided (SyntaxError). Cases
    # now ride as JSON data through the environment, never as generated code.
    provider = ScriptedProvider(
        {"spec": REVERSE_SPEC, "developer": "def reverse_string(s):\n    return s[::-1]\n"}
    )
    result = build_function("reverse a string", provider, MemoryStore(tmp_path))
    assert result.accepted


def test_missing_function_rejected_by_syntax_gate(tmp_path):
    provider = ScriptedProvider(
        {"spec": GOOD_SPEC, "developer": "def subtract(a, b):\n    return a - b\n"}
    )
    result = build_function("add", provider, MemoryStore(tmp_path))
    assert not result.accepted
    assert result.code_outcome is not None
    syntax_result = result.code_outcome.gate_results[0]
    assert syntax_result.gate_name == "syntax"
    assert not syntax_result.passed
