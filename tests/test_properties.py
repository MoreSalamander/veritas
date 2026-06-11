"""P13a — the structured-oracle vocabulary: parsing, and the harness biting for real.

These properties are oracle-free: every check is a relation over the function's OWN
outputs, never a model-authored value. The execution tests prove the harness passes
correct code and fails a mutant — with no `expected` anywhere.
"""

from __future__ import annotations

import json
import os

import pytest

from engine.executor import LocalSubprocessExecutor
from orgs.software_studio.properties import (
    INVARIANTS,
    PROPERTY_HARNESS,
    Property,
    PropertyKind,
    PropertyParseError,
    parse_properties,
    serialize,
)

_EXEC = LocalSubprocessExecutor()


def _run(code: str, fn: str, props: list[Property]) -> tuple[bool, str]:
    env = {**os.environ, "VERITAS_PROPS": serialize(props), "VERITAS_FN": fn}
    result = _EXEC.run(f"{code}\n{PROPERTY_HARNESS}", env, 10.0)
    last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
    return result.ok, last


# --- parsing / validation ---------------------------------------------------------


def test_parse_each_kind():
    props = parse_properties(
        [
            {"kind": "round_trip", "inverse": "dec", "inputs": [[1], [2]]},
            {"kind": "idempotent", "inputs": [[3]]},
            {"kind": "monotonic", "direction": "increasing", "inputs": [[1], [2]]},
            {"kind": "invariant", "invariant": "sorted_ascending", "inputs": [[[3, 1, 2]]]},
        ]
    )
    assert [p.kind for p in props] == [
        PropertyKind.ROUND_TRIP,
        PropertyKind.IDEMPOTENT,
        PropertyKind.MONOTONIC,
        PropertyKind.INVARIANT,
    ]


def test_empty_and_none_are_valid():
    assert parse_properties(None) == []
    assert parse_properties([]) == []


def test_round_trip_requires_inverse():
    with pytest.raises(PropertyParseError, match="inverse"):
        parse_properties([{"kind": "round_trip", "inputs": [[1]]}])


def test_monotonic_needs_two_inputs():
    with pytest.raises(PropertyParseError, match="at least 2"):
        parse_properties([{"kind": "monotonic", "inputs": [[1]]}])


def test_unknown_invariant_rejected():
    with pytest.raises(PropertyParseError, match="invariant"):
        parse_properties([{"kind": "invariant", "invariant": "is_prime", "inputs": [[1]]}])


def test_unknown_kind_rejected():
    with pytest.raises(PropertyParseError, match="unknown kind"):
        parse_properties([{"kind": "converges", "inputs": [[1]]}])


def test_idempotent_must_be_unary():
    with pytest.raises(PropertyParseError, match="one arg"):
        parse_properties([{"kind": "idempotent", "inputs": [[1, 2]]}])


def test_serialize_roundtrips_through_json():
    props = parse_properties([{"kind": "monotonic", "inputs": [[1], [2]], "strict": True}])
    back = json.loads(serialize(props))
    assert back[0] == {"kind": "monotonic", "inputs": [[1], [2]], "direction": "increasing", "strict": True}


def test_invariant_library_is_closed():
    assert "sorted_ascending" in INVARIANTS and "is_prime" not in INVARIANTS


# --- the harness actually bites (oracle-free, no expected values) ------------------

C2F = "def c2f(c):\n    return c * 9 / 5 + 32\n"
F2C = "def f2c(f):\n    return (f - 32) * 5 / 9\n"


def test_round_trip_passes_for_true_inverses():
    props = parse_properties([{"kind": "round_trip", "inverse": "f2c", "inputs": [[0], [100], [-40]]}])
    ok, _ = _run(C2F + F2C, "c2f", props)
    assert ok


def test_round_trip_fails_when_inverse_is_wrong():
    bad_f2c = "def f2c(f):\n    return f - 32\n"  # forgot the * 5/9
    props = parse_properties([{"kind": "round_trip", "inverse": "f2c", "inputs": [[100]]}])
    ok, last = _run(C2F + bad_f2c, "c2f", props)
    assert not ok and "round_trip" in last


def test_monotonic_passes_and_a_mutant_fails():
    props = parse_properties(
        [{"kind": "monotonic", "direction": "increasing", "inputs": [[-10], [0], [50], [100]]}]
    )
    ok, _ = _run(C2F, "c2f", props)
    assert ok
    mutant = "def c2f(c):\n    return -(c * 9 / 5 + 32)\n"  # negation flips the order
    ok2, last = _run(mutant, "c2f", props)
    assert not ok2 and "monotonic" in last


def test_invariant_sorted_ascending_bites():
    good = "def mysort(xs):\n    return sorted(xs)\n"
    props = parse_properties(
        [
            {"kind": "invariant", "invariant": "sorted_ascending", "inputs": [[[3, 1, 2]]]},
            {"kind": "invariant", "invariant": "is_permutation_of_input", "inputs": [[[3, 1, 2]]]},
        ]
    )
    ok, _ = _run(good, "mysort", props)
    assert ok
    dropping = "def mysort(xs):\n    return sorted(xs)[1:]\n"  # sorted but drops an element
    ok2, last = _run(dropping, "mysort", props)
    assert not ok2 and "is_permutation_of_input" in last


def test_idempotent_passes_and_a_mutant_fails():
    props = parse_properties([{"kind": "idempotent", "inputs": [[5], [-3]]}])
    ok, _ = _run("def absval(x):\n    return abs(x)\n", "absval", props)
    assert ok
    ok2, last = _run("def absval(x):\n    return x + 1\n", "absval", props)
    assert not ok2 and "idempotent" in last


def test_missing_function_is_a_clean_assertion():
    props = parse_properties([{"kind": "idempotent", "inputs": [[1]]}])
    ok, last = _run("def other(x):\n    return x\n", "absval", props)
    assert not ok and "absval" in last
