"""P8 — the Planner decomposes a goal into a validated multi-module plan (no code)."""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.software_studio.plan import build_plan, parse_plan

GOOD_PLAN = json.dumps(
    {
        "app_name": "todo",
        "modules": [
            {"module_name": "storage", "goal": "persist and load todo items"},
            {"module_name": "commands", "goal": "add, complete, and list todos"},
        ],
    }
)


def _provider(plan: str) -> ScriptedProvider:
    return ScriptedProvider({"planner": plan})


def test_clean_plan_accepted(tmp_path):
    result = build_plan("a todo app", _provider(GOOD_PLAN), MemoryStore(tmp_path))
    assert result.accepted
    assert result.plan_outcome.artifact.type == "plan"
    plan = parse_plan(result.plan_outcome.artifact.payload)
    assert [m.name for m in plan.modules] == ["storage", "commands"]


def test_plan_needs_two_modules(tmp_path):
    one = json.dumps({"app_name": "x", "modules": [{"module_name": "only", "goal": "do it all"}]})
    result = build_plan("x", _provider(one), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.plan_outcome.memory_path.parent.name == "failures"


def test_plan_rejects_duplicate_modules(tmp_path):
    dup = json.dumps({"app_name": "x", "modules": [
        {"module_name": "a", "goal": "one"}, {"module_name": "a", "goal": "two"}]})
    result = build_plan("x", _provider(dup), MemoryStore(tmp_path))
    assert not result.accepted


def test_prose_plan_rejected(tmp_path):
    result = build_plan("x", _provider("Sure! First we'll need a storage layer and..."),
                        MemoryStore(tmp_path))
    assert not result.accepted
    assert "not usable" in result.plan_outcome.artifact.provenance.gate_results[0].evidence
