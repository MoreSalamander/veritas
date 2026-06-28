"""P30b — the curated task battery for the trust benchmark.

Three tiers, chosen so the result is credible rather than cherry-picked:

  - EASY        — both contestants should ship correct (proves Veritas doesn't just refuse everything).
  - CATCHABLE   — a plausible wrong implementation VIOLATES an oracle-free property, so Veritas's HARD
                  gate refuses it while the bare agent ships it. This is where the architecture wins.
  - UNCATCHABLE — a pure value error that NO closed property distinguishes (multiply vs add, a scale
                  factor). Even with a sensible property declared, the wrong impl satisfies it, so
                  Veritas ALSO ships — flagging it soft, never false-greening. Included on purpose: a
                  benchmark that hides what the floor can't catch is propaganda.

Each entry carries a `reference_impl` (validates the hidden cases are right), a `plausible_wrong` (the
failure a model might actually ship), and a `reference_spec` (the oracle-free spec a competent proposer
would write). `test_trust_tasks.py` uses these to VERIFY the tier labels through the real gates offline:
a catchable wrong impl is refused, an uncatchable one ships. The real benchmark (P30c) hands only the
goal to a real model; this scaffolding is what proves the battery is honest before any model spends a token.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from bench.trust_bench import TrustTask


@dataclass
class BatteryEntry:
    task: TrustTask
    tier: str               # "easy" | "catchable" | "uncatchable"
    reference_impl: str     # a correct implementation
    plausible_wrong: str    # a wrong-but-plausible implementation a model might ship
    reference_spec: str     # the oracle-free spec a competent proposer would write (JSON)


def _spec(fn: str, desc: str, sig: str, cases: list[dict], properties: list[dict] | None = None) -> str:
    body: dict = {"function_name": fn, "description": desc, "signature": sig, "cases": cases}
    if properties:
        body["properties"] = properties
    return json.dumps(body)


# --- EASY: both should ship correct -----------------------------------------------------------
EASY = [
    BatteryEntry(
        TrustTask("double", "return the input number doubled", "double",
                  [([2], 4), ([0], 0), ([-3], -6)]),
        "easy",
        "def double(x):\n    return x * 2\n",
        "def double(x):\n    return x + 2\n",
        _spec("double", "double a number", "def double(x)", [{"args": [2], "expected": 4}]),
    ),
    BatteryEntry(
        TrustTask("maximum", "return the larger of two numbers", "maximum",
                  [([3, 7], 7), ([9, 2], 9), ([5, 5], 5)]),
        "easy",
        "def maximum(a, b):\n    return a if a > b else b\n",
        "def maximum(a, b):\n    return a if a < b else b\n",
        _spec("maximum", "larger of two", "def maximum(a, b)", [{"args": [3, 7], "expected": 7}]),
    ),
    BatteryEntry(
        TrustTask("string_length", "return the number of characters in a string", "string_length",
                  [(["hi"], 2), ([""], 0), (["abcd"], 4)]),
        "easy",
        "def string_length(s):\n    return len(s)\n",
        "def string_length(s):\n    return len(s) + 1\n",
        _spec("string_length", "length of a string", "def string_length(s)",
              [{"args": ["hi"], "expected": 2}]),
    ),
]

# --- CATCHABLE: a plausible wrong impl breaks an oracle-free property --------------------------
CATCHABLE = [
    BatteryEntry(
        TrustTask("sort", "sort a list of numbers ascending", "mysort",
                  [([[3, 1, 2]], [1, 2, 3]), ([[9, 0, 5, 5]], [0, 5, 5, 9])]),
        "catchable",
        "def mysort(xs):\n    return sorted(xs)\n",
        "def mysort(xs):\n    return sorted(xs)[1:]\n",  # sorted, but drops the smallest element
        _spec("mysort", "sort ascending", "def mysort(xs)", [{"args": [[3, 1, 2]], "expected": [1, 2, 3]}],
              [{"kind": "invariant", "invariant": "is_permutation_of_input", "inputs": [[[3, 1, 2]], [[9, 0, 5, 5]]]},
               {"kind": "invariant", "invariant": "sorted_ascending", "inputs": [[[3, 1, 2]], [[9, 0, 5, 5]]]}]),
    ),
    BatteryEntry(
        TrustTask("reverse_list", "return the list reversed", "reverse_list",
                  [([[1, 2, 3]], [3, 2, 1]), ([[5, 9, 2, 4]], [4, 2, 9, 5])]),
        "catchable",
        "def reverse_list(xs):\n    return xs[::-1]\n",
        "def reverse_list(xs):\n    return sorted(xs)\n",  # confuses "reverse" with "sort"
        _spec("reverse_list", "reverse a list", "def reverse_list(xs)",
              [{"args": [[1, 2, 3]], "expected": [3, 2, 1]}],
              [{"kind": "involution", "inputs": [[[3, 1, 2]], [[5, 9, 2, 4]]]}]),  # unsorted inputs
    ),
    BatteryEntry(
        TrustTask("negate", "return the additive inverse of a number", "negate",
                  [([3], -3), ([-7], 7), ([10], -10)]),
        "catchable",
        "def negate(x):\n    return -x\n",
        "def negate(x):\n    return abs(x)\n",  # right on positives, wrong on negatives
        _spec("negate", "additive inverse", "def negate(x)", [{"args": [3], "expected": -3}],
              [{"kind": "involution", "inputs": [[3], [-7]]}]),
    ),
    BatteryEntry(
        TrustTask("dedupe", "remove duplicate values, preserving first-seen order", "dedupe",
                  [([[1, 1, 2, 3, 3]], [1, 2, 3]), ([[5, 5, 5]], [5])]),
        "catchable",
        "def dedupe(xs):\n    return list(dict.fromkeys(xs))\n",
        "def dedupe(xs):\n    return list(xs)\n",  # forgets to actually dedupe
        _spec("dedupe", "remove duplicates", "def dedupe(xs)",
              [{"args": [[1, 1, 2, 3, 3]], "expected": [1, 2, 3]}],
              [{"kind": "invariant", "invariant": "elements_unique", "inputs": [[[1, 1, 2, 3, 3]]]},
               {"kind": "idempotent", "inputs": [[[1, 1, 2]]]}]),
    ),
]

# --- UNCATCHABLE: a value error no closed property pins (the honest limit) ---------------------
UNCATCHABLE = [
    BatteryEntry(
        TrustTask("rectangle_area", "return the area of a rectangle from width and height",
                  "rectangle_area", [([3, 4], 12), ([2, 5], 10), ([6, 1], 6)], catchable=False),
        "uncatchable",
        "def rectangle_area(w, h):\n    return w * h\n",
        "def rectangle_area(w, h):\n    return w + h\n",  # both are monotonic increasing — not distinguishable
        _spec("rectangle_area", "area of a rectangle", "def rectangle_area(w, h)",
              [{"args": [3, 4], "expected": 12}],
              [{"kind": "monotonic", "direction": "increasing", "inputs": [[1, 1], [2, 2], [3, 3]]}]),
    ),
    BatteryEntry(
        TrustTask("celsius_to_fahrenheit", "convert a celsius temperature to fahrenheit",
                  "celsius_to_fahrenheit", [([100], 212), ([20], 68), ([10], 50)], catchable=False),
        "uncatchable",
        "def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32\n",
        "def celsius_to_fahrenheit(c):\n    return c + 32\n",  # drops the scale factor; still monotonic
        _spec("celsius_to_fahrenheit", "celsius to fahrenheit", "def celsius_to_fahrenheit(c)",
              [{"args": [100], "expected": 212}],
              [{"kind": "monotonic", "direction": "increasing", "inputs": [[0], [50], [100]]}]),
    ),
    BatteryEntry(
        TrustTask("percent", "return what percent `part` is of `whole`", "percent",
                  [([1, 4], 25), ([2, 4], 50), ([3, 4], 75)], catchable=False),
        "uncatchable",
        "def percent(part, whole):\n    return part / whole * 100\n",
        "def percent(part, whole):\n    return part / whole\n",  # forgets the *100; still monotonic
        _spec("percent", "percent of whole", "def percent(part, whole)",
              [{"args": [1, 4], "expected": 25}],
              [{"kind": "monotonic", "direction": "increasing", "inputs": [[1, 4], [2, 4], [3, 4]]}]),
    ),
]

BATTERY: list[BatteryEntry] = EASY + CATCHABLE + UNCATCHABLE


def battery_tasks() -> list[TrustTask]:
    """Just the tasks (goal + hidden oracle), for handing to a real model in P30c."""
    return [e.task for e in BATTERY]
