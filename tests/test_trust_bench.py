"""P30a — the trust benchmark harness, proven offline with scripted models.

The point being demonstrated: given the SAME model output, the bare agent SHIPS a plausible-but-wrong
answer while Veritas REFUSES it — the only difference is the gate architecture. The judge is the
independent oracle (held-out reference cases), so the win isn't circular. The honest-limit case (a
value error no oracle-free property pins) is included so the report counts what Veritas can't catch too.
"""

from __future__ import annotations

import itertools
import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from engine.executor import LocalSubprocessExecutor
from bench.trust_bench import (
    TrustTask,
    Verdict,
    classify,
    judge,
    run_bare,
    run_battery,
    run_gate_isolation,
    run_veritas,
)

# --- specs/code mirroring the software org's own proven fixtures -------------------------------
SORT_SPEC = json.dumps({
    "function_name": "mysort", "description": "sort a list ascending", "signature": "def mysort(xs)",
    "cases": [{"args": [[3, 1, 2]], "expected": [1, 2, 3]}],
    "properties": [
        {"kind": "invariant", "invariant": "sorted_ascending", "inputs": [[[3, 1, 2]], [[9, 0, 5, 5]]]},
        {"kind": "invariant", "invariant": "is_permutation_of_input", "inputs": [[[3, 1, 2]], [[9, 0, 5, 5]]]},
    ],
})
GOOD_SORT = "def mysort(xs):\n    return sorted(xs)\n"
WRONG_SORT = "def mysort(xs):\n    return sorted(xs)[1:]\n"  # sorted but drops an element — CATCHABLE

ADD_SPEC = json.dumps({
    "function_name": "add", "description": "add two numbers", "signature": "def add(a, b)",
    "cases": [{"args": [1, 2], "expected": 3}, {"args": [5, 5], "expected": 10}],
})
WRONG_ADD = "def add(a, b):\n    return a - b\n"  # no oracle-free property pins a+b vs a-b — UNCATCHABLE

SORT_TASK = TrustTask("sort", "sort a list ascending", "mysort",
                      [([[3, 1, 2]], [1, 2, 3]), ([[9, 0, 5, 5]], [0, 5, 5, 9])],
                      catchable=True)
ADD_TASK = TrustTask("add", "add two numbers", "add",
                     [([1, 2], 3), ([5, 5], 10), ([-1, 1], 0)], catchable=False)

EX = LocalSubprocessExecutor()


def _mem_factory(tmp_path):
    c = itertools.count()
    return lambda: MemoryStore(tmp_path / f"mem{next(c)}")


# --- the independent judge actually distinguishes right from wrong -----------------------------

def test_judge_is_an_independent_oracle():
    assert judge(GOOD_SORT, SORT_TASK, EX) is True
    assert judge(WRONG_SORT, SORT_TASK, EX) is False   # drops an element → fails hidden cases
    assert judge(None, SORT_TASK, EX) is None


# --- THE MONEY CASE: same model output, opposite verdict ---------------------------------------

def test_same_model_output_bare_ships_veritas_refuses(tmp_path):
    provider = ScriptedProvider({"spec": SORT_SPEC, "developer": WRONG_SORT})
    bare = run_bare(SORT_TASK, provider)
    veritas = run_veritas(SORT_TASK, provider, MemoryStore(tmp_path / "m"))
    assert bare.code == veritas.code == WRONG_SORT  # identical model output…
    assert classify(SORT_TASK, bare, EX) == Verdict.SHIPPED_WRONG    # …bare ships it wrong…
    assert classify(SORT_TASK, veritas, EX) == Verdict.REFUSED_GOOD  # …the gates refuse it


def test_correct_code_both_ship(tmp_path):
    provider = ScriptedProvider({"spec": SORT_SPEC, "developer": GOOD_SORT})
    assert classify(SORT_TASK, run_bare(SORT_TASK, provider), EX) == Verdict.SHIPPED_CORRECT
    assert classify(SORT_TASK, run_veritas(SORT_TASK, provider, MemoryStore(tmp_path / "m")), EX) \
        == Verdict.SHIPPED_CORRECT


# --- gate isolation: same spec AND same code; only the gates differ ----------------------------

def test_gate_isolation_isolates_the_gates():
    provider = ScriptedProvider({"developer": WRONG_SORT})
    bare, veritas = run_gate_isolation(SORT_SPEC, SORT_TASK, provider)
    assert bare.code == veritas.code == WRONG_SORT          # one shared proposal…
    assert classify(SORT_TASK, bare, EX) == Verdict.SHIPPED_WRONG     # …bare ships it…
    assert classify(SORT_TASK, veritas, EX) == Verdict.REFUSED_GOOD   # …the gate alone refuses it


def test_gate_isolation_correct_code_both_ship():
    provider = ScriptedProvider({"developer": GOOD_SORT})
    bare, veritas = run_gate_isolation(SORT_SPEC, SORT_TASK, provider)
    assert classify(SORT_TASK, bare, EX) == Verdict.SHIPPED_CORRECT
    assert classify(SORT_TASK, veritas, EX) == Verdict.SHIPPED_CORRECT


def test_uncatchable_value_error_both_false_ship(tmp_path):
    # The honest limit: no oracle-free relation pins a+b vs a-b, so Veritas ships on the structural
    # gates too (flagging it soft) — it does NOT false-green by laundering a model number into hard.
    provider = ScriptedProvider({"spec": ADD_SPEC, "developer": WRONG_ADD})
    assert classify(ADD_TASK, run_bare(ADD_TASK, provider), EX) == Verdict.SHIPPED_WRONG
    assert classify(ADD_TASK, run_veritas(ADD_TASK, provider, MemoryStore(tmp_path / "m")), EX) \
        == Verdict.SHIPPED_WRONG


# --- the headline aggregation ------------------------------------------------------------------

def test_battery_headline(tmp_path):
    items = [
        (SORT_TASK, ScriptedProvider({"spec": SORT_SPEC, "developer": WRONG_SORT})),  # catchable wrong
        (SORT_TASK, ScriptedProvider({"spec": SORT_SPEC, "developer": GOOD_SORT})),   # correct
        (ADD_TASK, ScriptedProvider({"spec": ADD_SPEC, "developer": WRONG_ADD})),     # uncatchable wrong
    ]
    res = run_battery(items, _mem_factory(tmp_path), EX)
    # bare false-ships both wrong ones; Veritas false-ships only the uncatchable one
    assert res.bare.false_ship_rate == 2 / 3
    assert res.veritas.false_ship_rate == 1 / 3
    assert res.veritas.over_refusal_rate == 0.0  # it never wrongly rejected a correct answer
    # THE HEADLINE, on the catchable class: bare ships 1 wrong, Veritas ships 0
    assert res.catchable_false_ships() == (1, 0)
