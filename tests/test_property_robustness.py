"""Regression for a real over-refusal the trust benchmark (P30) surfaced: a model authored a property
with the wrong input shape, the hard property gate hit a runtime error evaluating it, and Veritas
rejected otherwise-CORRECT code. An errored gate is not a violated property — a malformed property is
uninformative and must be skipped, never a hard rejection. A genuine violation still fails hard.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from orgs.software_studio.gates import PropertyGate
from orgs.software_studio.properties import parse_properties


def _props(s: str):
    return parse_properties(json.loads(s))


def _art(code: str) -> Artifact:
    return Artifact.propose(type="code", owner="t", payload=code, rationale="t")


def test_malformed_property_does_not_reject_correct_code():
    # correct dedupe, but the property's input is a scalar where a list is expected → the invariant
    # check raises a TypeError. That's the PROPERTY's fault, not the code's — it must not hard-reject.
    code = "def f(xs):\n    return list(dict.fromkeys(xs))\n"
    props = _props('[{"kind": "invariant", "invariant": "is_permutation_of_input", "inputs": [[5]]}]')
    res = PropertyGate("f", props).check(_art(code))
    assert res.passed and "skipped" in res.evidence.lower()


def test_malformed_property_alongside_a_real_one_still_honors_the_real_one():
    # a valid involution property holds; a malformed second property is skipped — the code ships.
    code = "def f(xs):\n    return xs[::-1]\n"
    props = _props(
        '[{"kind": "involution", "inputs": [[[3, 1, 2]]]},'
        ' {"kind": "invariant", "invariant": "elements_unique", "inputs": [[7]]}]')  # 7 is not iterable
    res = PropertyGate("f", props).check(_art(code))
    assert res.passed


def test_a_real_violation_still_fails_hard():
    # sorted-but-drops-an-element cleanly violates is_permutation_of_input → still a hard rejection
    code = "def f(xs):\n    return sorted(xs)[1:]\n"
    props = _props(
        '[{"kind": "invariant", "invariant": "is_permutation_of_input", "inputs": [[[3, 1, 2]]]}]')
    res = PropertyGate("f", props).check(_art(code))
    assert not res.passed and "permutation" in res.evidence
