"""hub/tutorial_generate.py — offline, deterministic.

The gate is the whole point: a generated tutorial that respects the interview's scope AND
actually has materials (ingredients/tools/prerequisites) and real steps passes; one missing
either, or inventing code the person didn't ask for, is rejected — same "model proposes,
deterministic check decides" discipline as every other gate in this codebase.
"""

from __future__ import annotations

import json

from engine.memory import MemoryRecord
from engine.model import SequencedProvider
from hub.tutorial_generate import (
    TutorialContent,
    TutorialSection,
    TutorialStep,
    content_completeness,
    generate_tutorial,
    parse_tutorial_content,
)
from hub.tutorial_spec import TutorialSpec


def _source() -> MemoryRecord:
    return MemoryRecord.from_source(
        url="https://example.com/vid",
        transcript="some real transcript text about widgets",
        title="How Widgets Work",
        channel="ExampleChannel",
    )


def _good_payload(**overrides: object) -> str:
    payload = {
        "overview": "Build a widget from scratch.",
        "materials": ["1 frobnicator", "2 gaskets"],
        "sections": [
            {"title": "Assemble", "intro": "", "tip": "",
             "steps": [{"instruction": "Attach the frobnicator.", "code": ""}]},
        ],
        "reference": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_tutorial_content_reads_all_fields():
    content = parse_tutorial_content(_good_payload(reference=["torque: 5 Nm"]))
    assert content.overview == "Build a widget from scratch."
    assert content.materials == ["1 frobnicator", "2 gaskets"]
    assert len(content.sections) == 1
    assert content.sections[0].title == "Assemble"
    assert content.sections[0].steps == [TutorialStep(instruction="Attach the frobnicator.", code="")]
    assert content.reference == ["torque: 5 Nm"]


def test_completeness_requires_an_overview():
    empty = TutorialContent(overview="", materials=["x"], sections=[TutorialSection("A", [TutorialStep("do it")])])
    ok, missing = content_completeness(empty, TutorialSpec("overview", "essentials_only", False))
    assert not ok and "overview" in missing


def test_completeness_requires_materials():
    # The exact defect this schema exists to prevent: a recipe with no ingredients.
    content = TutorialContent(
        overview="Make a souffle.", materials=[],
        sections=[TutorialSection("Bake", [TutorialStep("Bake it.")])],
    )
    ok, missing = content_completeness(content, TutorialSpec("walkthrough", "detailed", False))
    assert not ok and any("materials" in m for m in missing)


def test_completeness_requires_sections():
    content = TutorialContent(overview="x", materials=["y"], sections=[])
    ok, missing = content_completeness(content, TutorialSpec("overview", "essentials_only", False))
    assert not ok and "sections" in missing


def test_completeness_rejects_uninvited_step_code():
    spec = TutorialSpec("overview", "essentials_only", include_typing_practice=False)
    content = TutorialContent(
        overview="x", materials=["y"],
        sections=[TutorialSection("A", [TutorialStep("do it", code="def f(): pass")])],
    )
    ok, missing = content_completeness(content, spec)
    assert not ok and any("code" in m for m in missing)


def test_completeness_allows_step_code_when_requested():
    spec = TutorialSpec("walkthrough", "detailed", include_typing_practice=True)
    content = TutorialContent(
        overview="x", materials=["y"],
        sections=[TutorialSection("A", [TutorialStep("do it", code="def f(): pass")])],
    )
    ok, missing = content_completeness(content, spec)
    assert ok and missing == []


def test_generate_tutorial_accepts_a_scope_respecting_artifact():
    spec = TutorialSpec("overview", "essentials_only", include_typing_practice=False)
    provider = SequencedProvider({"tutorial-generator": [_good_payload()]})
    artifact, result = generate_tutorial(_source(), spec, provider)
    assert result.passed
    assert artifact.status.value == "accepted"


def test_generate_tutorial_rejects_missing_materials():
    spec = TutorialSpec("overview", "essentials_only", include_typing_practice=False)
    bad = json.dumps({"overview": "x", "materials": [], "sections": [
        {"title": "A", "steps": [{"instruction": "do it"}]},
    ]})
    provider = SequencedProvider({"tutorial-generator": [bad]})
    artifact, result = generate_tutorial(_source(), spec, provider)
    assert not result.passed
    assert artifact.status.value == "rejected"


def test_generate_tutorial_rejects_uninvited_code():
    spec = TutorialSpec("overview", "essentials_only", include_typing_practice=False)
    bad = _good_payload(sections=[
        {"title": "A", "steps": [{"instruction": "do it", "code": "def f(): pass"}]},
    ])
    provider = SequencedProvider({"tutorial-generator": [bad]})
    artifact, result = generate_tutorial(_source(), spec, provider)
    assert not result.passed
    assert artifact.status.value == "rejected"
