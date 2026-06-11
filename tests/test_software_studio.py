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

# A spec carrying an ORACLE-FREE property (P13): the output must be a sorted permutation
# of the input. No `expected` value is trusted — the relation is checked over the
# function's own output, so the HARD property gate, not a model number, makes the call.
SORT_SPEC = json.dumps(
    {
        "function_name": "mysort",
        "description": "sort a list ascending",
        "signature": "def mysort(xs)",
        "cases": [{"args": [[3, 1, 2]], "expected": [1, 2, 3]}],
        "properties": [
            {"kind": "invariant", "invariant": "sorted_ascending", "inputs": [[[3, 1, 2]], [[9, 0, 5, 5]]]},
            {"kind": "invariant", "invariant": "is_permutation_of_input", "inputs": [[[3, 1, 2]], [[9, 0, 5, 5]]]},
        ],
    }
)
GOOD_SORT = "def mysort(xs):\n    return sorted(xs)\n"
WRONG_SORT = "def mysort(xs):\n    return sorted(xs)[1:]\n"  # sorted, but drops an element


def test_good_run_earns_code_into_memory(tmp_path):
    provider = ScriptedProvider({"spec": GOOD_SPEC, "developer": GOOD_CODE})
    result = build_function("add two numbers", provider, MemoryStore(tmp_path))

    assert result.accepted
    assert result.spec_outcome.accepted
    assert result.code_outcome is not None and result.code_outcome.accepted
    assert result.code_outcome.memory_path.parent.name == "institutional"
    assert "all hard gates passed" in (result.code_outcome.artifact.provenance.accepted_because or "")


def test_prose_spec_rejected_before_any_code(tmp_path):
    provider = ScriptedProvider({"spec": PROSE_SPEC, "developer": GOOD_CODE})
    result = build_function("add", provider, MemoryStore(tmp_path))

    assert not result.accepted
    assert not result.spec_outcome.accepted
    assert result.code_outcome is None  # the developer never ran
    assert result.spec_outcome.memory_path.parent.name == "failures"
    assert "not executable" in result.spec_outcome.memory_path.read_text()


def test_wrong_code_rejected_by_property_gate(tmp_path):
    # The HARD authority is the oracle-free property, not a model-authored case. Code that
    # sorts but drops an element breaks is_permutation_of_input — and is hard-rejected
    # without trusting any `expected` value.
    provider = ScriptedProvider({"spec": SORT_SPEC, "developer": WRONG_SORT})
    result = build_function("sort a list", provider, MemoryStore(tmp_path))

    assert result.spec_outcome.accepted
    assert not result.accepted
    assert result.code_outcome is not None
    assert result.code_outcome.memory_path.parent.name == "failures"
    prop = next(g for g in result.code_outcome.gate_results if g.gate_name == "properties")
    assert not prop.passed and "permutation" in prop.evidence


def test_good_code_passes_the_property_gate(tmp_path):
    provider = ScriptedProvider({"spec": SORT_SPEC, "developer": GOOD_SORT})
    result = build_function("sort a list", provider, MemoryStore(tmp_path))
    assert result.accepted
    prop = next(g for g in result.code_outcome.gate_results if g.gate_name == "properties")
    assert prop.passed and prop.determinism.value == "hard"


def test_value_error_with_no_property_is_advisory_not_a_hard_block(tmp_path):
    # The honest limit of P13: no oracle-free relation distinguishes a+b from a-b, so a
    # value error here cannot be hard-caught without trusting the model's number. The
    # scaffold refuses to do that — it ships on the structural hard gates and records the
    # exact-value discrepancy as an ADVISORY (soft) finding rather than laundering a model
    # oracle into a hard verdict. This is the architecture being honest about what it can
    # and cannot guarantee.
    provider = ScriptedProvider({"spec": GOOD_SPEC, "developer": WRONG_CODE})
    result = build_function("add", provider, MemoryStore(tmp_path))

    assert result.accepted  # passes the structural HARD gates; no property pins the value
    assert result.code_outcome is not None
    props = next(g for g in result.code_outcome.gate_results if g.gate_name == "properties")
    assert props.passed and "not hard-verified" in props.evidence
    acc = next(g for g in result.code_outcome.gate_results if g.gate_name == "acceptance-tests")
    assert acc.determinism.value == "soft" and not acc.passed  # flagged, advisory


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
