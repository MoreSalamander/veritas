"""The university end to end, offline: roadmap verified, concept researched
in parallel, lesson gated for grounding + answerability, mastery moving
only through graded assessment — and the next session starting where the
learner actually is."""

import json

from commons.parallel_client import ExtractResult, ScriptedSearchClient, SearchResult
from engine.memory import MemoryStore
from engine.model import SequencedProvider
from orgs.education_studio.curriculum import EDU_ANGLES
from orgs.education_studio.pipeline import LearnerStore, build_learning, record_grade

ROADMAP = json.dumps({
    "concepts": [
        {"name": "Vectors", "summary": "arrows with meaning"},
        {"name": "Regression", "summary": "fitting lines"},
    ],
    "edges": [{"source": "Vectors", "relation": "requires", "target": "Regression"}],
})

LESSON = json.dumps({
    "concept": "Vectors",
    "sections": [
        {"title": "The idea", "body": "A vector has direction and magnitude.", "cites": ["src1"]},
    ],
    "quiz": [
        {"question": "What does a vector have?",
         "options": ["direction and magnitude", "flavor"],
         "answer_index": 0, "answer_span": "direction and magnitude"},
    ],
})


def _search(concept="Vectors"):
    return ScriptedSearchClient(
        search_by_query={
            f"{concept} {EDU_ANGLES['academic'][0]}": [
                SearchResult(url="https://mit.example/la", title="Course"),
            ],
        },
        extract_by_url={
            "https://mit.example/la": ExtractResult(
                url="https://mit.example/la", title="Course",
                content="A vector has direction and magnitude."),
        },
    )


def test_full_session_and_mastery_only_through_grading(tmp_path):
    provider = SequencedProvider({"researcher": [ROADMAP, LESSON]})
    memory = MemoryStore(tmp_path / "m")
    res = build_learning("teach me machine learning", provider, memory, _search())

    assert res.accepted and res.concept == "Vectors", "first unlearned prerequisite leads"
    assert res.lesson is not None
    gates = [g.gate_name for g in res.lesson_outcome.artifact.provenance.gate_results]
    assert gates == ["lesson-contract", "validation"]
    assert {s.angle for s in res.sources} == {"academic"}, "dead angles return nothing, honestly"

    # Mastery hasn't moved yet — teaching is not assessment.
    assert LearnerStore(memory).load().known == {}

    graded = record_grade(memory, "Vectors", res.lesson, [0])
    assert graded["mastered"] is True and graded["score"] == 1.0
    model = LearnerStore(memory).load()
    assert model.known["Vectors"] == 1.0

    # Concept graph persisted for the knowledge layer.
    titles = {r.title for r in memory.load_all() if r.category == "entity"}
    assert "concept:Vectors" in titles and "concept:Regression" in titles


def test_next_session_skips_what_was_proven(tmp_path):
    memory = MemoryStore(tmp_path / "m")
    provider = SequencedProvider({"researcher": [ROADMAP, LESSON]})
    res = build_learning("teach me machine learning", provider, memory, _search())
    record_grade(memory, "Vectors", res.lesson, [0])

    lesson2 = LESSON.replace('"Vectors"', '"Regression"').replace(
        "A vector has direction and magnitude.",
        "Regression fits a line minimizing squared error.").replace(
        '"answer_span": "direction and magnitude"',
        '"answer_span": "minimizing squared error"').replace(
        '"options": ["direction and magnitude", "flavor"]',
        '"options": ["minimizing squared error", "flavor"]')
    provider2 = SequencedProvider({"researcher": [ROADMAP, lesson2]})
    res2 = build_learning("teach me machine learning", provider2, memory, _search("Regression"))

    assert res2.roadmap.skipped == ["Vectors"], "the proven concept is skipped, and shown"
    assert res2.concept == "Regression", "the university moved to the next rung"


def test_failing_grade_marks_weak_not_mastered(tmp_path):
    provider = SequencedProvider({"researcher": [ROADMAP, LESSON]})
    memory = MemoryStore(tmp_path / "m")
    res = build_learning("ml", provider, memory, _search())
    graded = record_grade(memory, "Vectors", res.lesson, [1])
    assert graded["mastered"] is False
    model = LearnerStore(memory).load()
    assert "Vectors" in model.weak and model.known["Vectors"] == 0.0
