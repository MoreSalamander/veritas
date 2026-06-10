"""Phase 3 definition-of-done — the org learns.

Proven offline:
- recall() finds relevant past records and ignores unrelated ones (deterministic).
- A run records what memory informed it (provenance.informed_by), on disk.
- The thesis test: a proposer that fails when uninformed but succeeds once its own
  prior failure is recalled. The first run fails and is remembered; the second run,
  warned by that memory, avoids the mistake. That is the organization learning.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact, Provenance
from engine.memory import MemoryRecord, MemoryStore
from engine.model import ModelProvider
from orgs.software_studio.pipeline import build_software

GOOD_SPEC = json.dumps(
    {
        "function_name": "reverse_string",
        "description": "reverse a string",
        "signature": "def reverse_string(s)",
        "cases": [
            {"args": ["hello"], "expected": "olleh"},
            {"args": ["abc"], "expected": "cba"},
            {"args": [""], "expected": ""},
        ],
    }
)
GOOD_CODE = "def reverse_string(s):\n    return s[::-1]\n"
PROSE_SPEC = "Sure — you want something that flips a string around end to end."


def _failure_record(goal_words: str) -> MemoryRecord:
    art = Artifact(
        type="spec",
        owner="spec-agent",
        payload="(prose)",
        provenance=Provenance(created_by="spec-agent", rationale=f"specification for goal: {goal_words}"),
    )
    return MemoryRecord.from_rejected_artifact(art, reason="spec not executable: no cases")


def test_recall_finds_related_and_skips_unrelated(tmp_path):
    store = MemoryStore(tmp_path)
    store.persist(_failure_record("reverse a string"))

    hits = store.recall("a function that reverses a string")
    assert len(hits) == 1

    misses = store.recall("compute the monthly mortgage payment")
    assert misses == []


def test_recall_can_filter_by_category(tmp_path):
    store = MemoryStore(tmp_path)
    store.persist(MemoryRecord(category="lesson", title="reverse strings carefully",
                               body="prefer slicing", tags=["reverse"]))
    assert len(store.recall("reverse a string", categories=["lesson"])) == 1
    assert store.recall("reverse a string", categories=["failure"]) == []


class _LearningProvider(ModelProvider):
    """Fails the spec when uninformed; succeeds once a prior lesson is in the prompt.
    A deterministic stand-in for 'a model that does better when warned.'"""

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        if role == "spec":
            return GOOD_SPEC if "past attempts" in prompt else PROSE_SPEC
        if role == "developer":
            return GOOD_CODE
        if role == "qa":
            return "[]"
        raise KeyError(role)


def test_org_avoids_repeating_its_own_failure(tmp_path):
    memory = MemoryStore(tmp_path)
    provider = _LearningProvider()
    goal = "a function that reverses a string"

    # Run 1: nothing recalled, the proposer fumbles the spec, it's rejected & remembered.
    first = build_software(goal, provider, memory)
    assert not first.accepted
    assert first.informed_by == []
    assert first.spec_outcome.memory_path.parent.name == "failures"
    failure_id = first.spec_outcome.memory_path.stem

    # Run 2: the failure is recalled, injected, and the proposer now succeeds.
    second = build_software(goal, provider, memory)
    assert second.accepted
    assert failure_id in second.informed_by  # the recalled memory that shaped it
    assert second.code_outcome is not None
    assert failure_id in second.code_outcome.artifact.provenance.informed_by


def test_informed_by_is_persisted_to_disk(tmp_path):
    memory = MemoryStore(tmp_path)
    provider = _LearningProvider()
    goal = "a function that reverses a string"

    build_software(goal, provider, memory)  # seeds a failure
    second = build_software(goal, provider, memory)

    assert second.code_outcome is not None
    text = second.code_outcome.memory_path.read_text()
    assert "informed_by:" in text
    assert second.informed_by[0] in text
