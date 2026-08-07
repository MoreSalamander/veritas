"""The university's contracts: DAG-or-refusal, honest personalization,
answerable quizzes, deterministic grading."""

import pytest

from orgs.education_studio.curriculum import (
    LearnerModel,
    RoadmapParseError,
    parse_roadmap,
)
from orgs.education_studio.lesson import (
    LessonParseError,
    grade,
    parse_lesson,
    render_lesson_markdown,
    unanswerable,
)

ROADMAP = """{
  "concepts": [
    {"name": "Linear Algebra", "summary": "vectors and matrices"},
    {"name": "Python", "summary": "the working language"},
    {"name": "Regression", "summary": "fitting lines to data"},
    {"name": "Neural Networks", "summary": "stacked learned functions"}
  ],
  "edges": [
    {"source": "Linear Algebra", "relation": "requires", "target": "Regression"},
    {"source": "Python", "relation": "requires", "target": "Regression"},
    {"source": "Regression", "relation": "builds_upon", "target": "Neural Networks"}
  ]
}"""


def test_roadmap_orders_by_prerequisites():
    plan = parse_roadmap(ROADMAP, "machine learning", LearnerModel())
    assert plan.order.index("Linear Algebra") < plan.order.index("Regression")
    assert plan.order.index("Regression") < plan.order.index("Neural Networks")
    assert plan.path == plan.order and plan.skipped == []


def test_personalization_is_subtraction_and_shown():
    learner = LearnerModel(known={"Linear Algebra": 0.9, "Python": 0.85})
    plan = parse_roadmap(ROADMAP, "machine learning", learner)
    assert plan.skipped == ["Linear Algebra", "Python"]
    assert plan.path[0] == "Regression", "the first unlearned concept leads"
    assert "skipping 2 concept(s) you've already proven" in plan.brief()


def test_cycle_is_refused_not_repaired():
    cyclic = ROADMAP.replace(
        '{"source": "Regression", "relation": "builds_upon", "target": "Neural Networks"}',
        '{"source": "Regression", "relation": "builds_upon", "target": "Neural Networks"},'
        '{"source": "Neural Networks", "relation": "requires", "target": "Linear Algebra"}',
    )
    with pytest.raises(RoadmapParseError, match="cycle"):
        parse_roadmap(cyclic, "ml", LearnerModel())


def test_invented_relation_and_ghost_concept_refused():
    with pytest.raises(RoadmapParseError, match="not in"):
        parse_roadmap(ROADMAP.replace('"requires"', '"vibes_into"', 1), "ml", LearnerModel())
    with pytest.raises(RoadmapParseError, match="undeclared concept"):
        parse_roadmap(ROADMAP.replace('"target": "Regression"', '"target": "Quantum Vibes"', 1),
                      "ml", LearnerModel())


LESSON = """{
  "concept": "Regression",
  "sections": [
    {"title": "The idea", "body": "Regression fits a line that minimizes squared error.", "cites": ["src1"]},
    {"title": "In practice", "body": "You fit with least squares and read the slope.", "cites": ["src2"]}
  ],
  "quiz": [
    {"question": "What does regression minimize?", "options": ["squared error", "runtime"],
     "answer_index": 0, "answer_span": "minimizes squared error"}
  ],
  "exercises": ["Fit a line to five points by hand."],
  "socratic": ["Why square the error instead of taking absolute value?"]
}"""


def test_lesson_parses_grounded_and_answerable():
    lesson = parse_lesson(LESSON, corpus_ids={"src1", "src2"})
    assert unanswerable(lesson) == []
    page = render_lesson_markdown(lesson, source_urls={"src1": "https://a.example"})
    assert "## The idea" in page and "[src1]" in page
    assert "Socratic, unanswered on purpose" in page


def test_uncited_section_and_ghost_source_refused():
    with pytest.raises(LessonParseError, match="cites nothing"):
        parse_lesson(LESSON.replace('"cites": ["src2"]', '"cites": []'), {"src1", "src2"})
    with pytest.raises(LessonParseError, match="not in the education corpus"):
        parse_lesson(LESSON, corpus_ids={"src1"})


def test_unanswerable_quiz_is_detected():
    lesson = parse_lesson(
        LESSON.replace("minimizes squared error", "maximizes vibes coefficient", 1)
        if False else LESSON.replace('"answer_span": "minimizes squared error"',
                                     '"answer_span": "maximizes the vibe"'),
        corpus_ids={"src1", "src2"},
    )
    assert unanswerable(lesson) == [0], "a quiz the lesson can't answer is caught"


def test_grading_is_deterministic_and_index_exact():
    lesson = parse_lesson(LESSON, corpus_ids={"src1", "src2"})
    result = grade(lesson, [0])
    assert result["score"] == 1.0 and result["correct"] == 1
    result = grade(lesson, [1])
    assert result["score"] == 0.0 and result["per_question"][0]["right"] is False
    result = grade(lesson, [])
    assert result["score"] == 0.0, "an unanswered question is wrong, not skipped"
