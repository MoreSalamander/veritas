"""P30b — validate the task battery is honest BEFORE any model spends a token.

Three things are checked offline: (1) every reference implementation passes its own hidden cases (the
oracle is right), (2) every plausible-wrong implementation fails them (the task discriminates), and
(3) the tier labels are real — a CATCHABLE wrong impl is actually refused by the gates, an UNCATCHABLE
one actually ships (the honest limit). If a "catchable" task didn't fail the gate, the headline would
be a lie; this test makes the labels load-bearing.
"""

from __future__ import annotations

import itertools

import pytest

from engine.executor import LocalSubprocessExecutor
from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.software_studio.pipeline import build_function
from bench.trust_bench import judge
from bench.trust_tasks import BATTERY, CATCHABLE, EASY, HARD, UNCATCHABLE, battery_tasks

EX = LocalSubprocessExecutor()


def test_battery_has_all_tiers_including_the_honest_limit():
    assert len(EASY) == 3 and len(CATCHABLE) == 4 and len(UNCATCHABLE) == 3 and len(HARD) == 4
    assert len(battery_tasks()) == len(BATTERY) == 14
    # the uncatchable tier MUST exist — its absence would make the benchmark propaganda
    assert any(e.tier == "uncatchable" for e in BATTERY)
    assert all(e.task.catchable for e in CATCHABLE + HARD)
    assert all(not e.task.catchable for e in UNCATCHABLE)


@pytest.mark.parametrize("entry", BATTERY, ids=[e.task.name for e in BATTERY])
def test_reference_impl_passes_hidden_cases(entry):
    assert judge(entry.reference_impl, entry.task, EX) is True


@pytest.mark.parametrize("entry", BATTERY, ids=[e.task.name for e in BATTERY])
def test_plausible_wrong_fails_hidden_cases(entry):
    assert judge(entry.plausible_wrong, entry.task, EX) is False


def _accepts(spec: str, code: str, tmp_path, n) -> bool:
    provider = ScriptedProvider({"spec": spec, "developer": code})
    return build_function("t", provider, MemoryStore(tmp_path / f"m{n}")).accepted


@pytest.mark.parametrize("entry", CATCHABLE + HARD, ids=[e.task.name for e in CATCHABLE + HARD])
def test_catchable_label_is_real(entry, tmp_path):
    c = itertools.count()
    # the gate refuses the plausible-wrong impl…
    assert _accepts(entry.reference_spec, entry.plausible_wrong, tmp_path, next(c)) is False
    # …and accepts the correct one (the property isn't over-strict)
    assert _accepts(entry.reference_spec, entry.reference_impl, tmp_path, next(c)) is True


@pytest.mark.parametrize("entry", UNCATCHABLE, ids=[e.task.name for e in UNCATCHABLE])
def test_uncatchable_label_is_real(entry, tmp_path):
    c = itertools.count()
    # even with a sensible property declared, the wrong impl satisfies it → it SHIPS (the honest limit,
    # not laziness — a property IS declared; it just can't express the value error)
    assert _accepts(entry.reference_spec, entry.plausible_wrong, tmp_path, next(c)) is True
    assert _accepts(entry.reference_spec, entry.reference_impl, tmp_path, next(c)) is True
