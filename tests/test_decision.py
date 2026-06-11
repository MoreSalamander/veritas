"""P11 — the Memory seat: a shipped build's decision is recorded and surfaces on related work.

Proven offline: an accepted build writes a decision record (category "decision"); a later
related build recalls it and it shapes the new run's provenance (informed_by); rejected
builds record no decision; and decisions are injected under a "for consistency" framing
distinct from failure lessons.
"""

from __future__ import annotations

import json

from engine.memory import MemoryRecord, MemoryStore, format_lessons
from engine.model import ScriptedProvider
from orgs.software_studio.builder import build

SPEC = json.dumps(
    {"function_name": "f2c", "description": "f to c", "signature": "def f2c(f)",
     "cases": [{"args": [32], "expected": 0}]}
)
CODE = "def f2c(f):\n    return (f - 32) * 5 / 9\n"
DOC = "# f2c\n\n```python\nassert f2c(32) == 0\n```\n"


def _provider() -> ScriptedProvider:
    return ScriptedProvider({"router": "function", "spec": SPEC, "developer": CODE, "qa": "[]", "doc": DOC})


def test_decision_recorded_and_recalled_on_related_build(tmp_path):
    memory = MemoryStore(tmp_path)

    first = build("convert fahrenheit to celsius", _provider(), memory)
    assert first.accepted
    decisions = [m for m in memory.load_all() if m.category == "decision"]
    assert len(decisions) == 1 and decisions[0].provenance.get("shape") == "function"
    decision_id = decisions[0].id

    second = build("a celsius and fahrenheit converter", _provider(), memory)
    assert second.accepted
    # the prior decision was recalled and stamped into the new build's provenance.
    assert decision_id in second.outcomes[0].artifact.provenance.informed_by


def test_no_decision_recorded_when_build_rejected(tmp_path):
    memory = MemoryStore(tmp_path)
    bad = ScriptedProvider({"router": "function", "spec": "just prose", "developer": CODE, "qa": "[]", "doc": DOC})
    result = build("x", bad, memory)
    assert not result.accepted
    assert not any(m.category == "decision" for m in memory.load_all())


def test_decisions_injected_separately_from_failures():
    decision = MemoryRecord.from_decision(
        goal="reverse a string", shape="function", artifact_types=["spec", "code"], source_ids=["a"]
    )
    out = format_lessons([decision]) or ""
    assert "structured similar goals before" in out
    assert "reverse a string" in out
    assert "avoid repeating" not in out  # a decision is reference, not a warning
