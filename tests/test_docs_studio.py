"""Phase 5 definition-of-done — a second org type on the unchanged substrate.

The Docs Studio produces a different kind of artifact (a document) with a different
cast, yet rides the same Artifact / Gate / Memory / Run / Executor / Validation engine.
Proven offline: a clean doc is earned into the SAME memory with the SAME provenance
shape; a doc with a broken example is hard-rejected by examples-run; a missing section
is hard-rejected by structure; a thin doc is soft-flagged but still accepted. The final
gate is the shared engine ValidationGate — the proof that only the cast changed.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.docs_studio.pipeline import build_doc

OUTLINE = json.dumps(
    {"title": "List comprehensions", "sections": ["What they are", "Example"], "min_examples": 1}
)

GOOD_DOC = (
    "# List comprehensions\n\n"
    "## What they are\n"
    "A list comprehension is a compact way to build a list from an iterable in a single "
    "readable expression, instead of writing an explicit for-loop with append calls.\n\n"
    "## Example\n"
    "```python\n"
    "squares = [x * x for x in range(5)]\n"
    "assert squares == [0, 1, 4, 9, 16]\n"
    "print(squares)\n"
    "```\n"
)

# Structurally fine, example runs, but almost no prose -> readability soft-flags it.
THIN_DOC = (
    "# List comprehensions\n\n"
    "## What they are\nLists.\n\n"
    "## Example\n```python\nassert [x for x in range(3)] == [0, 1, 2]\n```\n"
)

# A broken example -> examples-run must hard-reject.
BROKEN_DOC = GOOD_DOC.replace("assert squares == [0, 1, 4, 9, 16]", "assert squares == [9, 9, 9]")

# Missing the 'Example' section -> structure must hard-reject.
MISSING_SECTION_DOC = "# List comprehensions\n\n## What they are\nLists are useful here.\n"


def _provider(outline: str, doc: str) -> ScriptedProvider:
    return ScriptedProvider({"outline": outline, "writer": doc})


def test_clean_doc_earned_into_shared_memory(tmp_path):
    result = build_doc("list comprehensions", _provider(OUTLINE, GOOD_DOC), MemoryStore(tmp_path))
    assert result.accepted
    assert result.doc_outcome is not None
    gate_names = [g.gate_name for g in result.doc_outcome.artifact.provenance.gate_results]
    # Domain gates plus the shared engine final authority.
    assert gate_names == ["structure", "examples-run", "readability", "validation"]
    assert result.doc_outcome.artifact.type == "document"
    assert result.doc_outcome.memory_path.parent.name == "institutional"


def test_broken_example_is_hard_rejected(tmp_path):
    result = build_doc("x", _provider(OUTLINE, BROKEN_DOC), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.doc_outcome is not None
    examples = next(
        g for g in result.doc_outcome.artifact.provenance.gate_results if g.gate_name == "examples-run"
    )
    assert not examples.passed
    assert result.doc_outcome.memory_path.parent.name == "failures"


def test_missing_section_is_hard_rejected(tmp_path):
    result = build_doc("x", _provider(OUTLINE, MISSING_SECTION_DOC), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.doc_outcome is not None
    structure = next(
        g for g in result.doc_outcome.artifact.provenance.gate_results if g.gate_name == "structure"
    )
    assert not structure.passed


def test_thin_doc_soft_flagged_but_accepted(tmp_path):
    result = build_doc("x", _provider(OUTLINE, THIN_DOC), MemoryStore(tmp_path))
    assert result.accepted  # hard gates pass; readability only advises
    assert result.doc_outcome is not None
    readability = next(
        g for g in result.doc_outcome.artifact.provenance.gate_results if g.gate_name == "readability"
    )
    assert readability.determinism.value == "soft" and not readability.passed
    assert "soft findings noted" in (result.doc_outcome.artifact.provenance.accepted_because or "")


def test_prose_outline_rejected_before_writing(tmp_path):
    result = build_doc("x", _provider("Sure, here is a plan for the doc!", GOOD_DOC),
                       MemoryStore(tmp_path))
    assert not result.accepted
    assert result.doc_outcome is None  # the writer never ran
    assert result.outline_outcome.memory_path.parent.name == "failures"
