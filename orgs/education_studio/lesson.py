"""The lesson contract: taught claims are grounded, quizzes are answerable.

Two deterministic properties separate a verified lesson from confident
prose:

* **Grounding** — every section cites at least one source from the
  education corpus by id, cited ids must resolve, and any verbatim quote
  must actually appear in its source (the research studio's normalize fold
  reused — typography never decides truth).
* **Answerability** — every quiz question carries an ``answer_span`` that
  must appear in the lesson's own sections. A quiz you cannot answer from
  the lesson taught is refused. Grading is index-exact and deterministic.

Socratic questions and exercises ship labeled as what they are: proposals
for the learner, not verified facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from orgs.research_studio.report import normalize


class LessonParseError(ValueError):
    """The proposed lesson is not usable."""


@dataclass
class QuizItem:
    question: str
    options: list[str]
    answer_index: int
    answer_span: str  # must appear in the lesson body — answerability, checked


@dataclass
class LessonSection:
    title: str
    body: str
    cites: list[str]


@dataclass
class Lesson:
    concept: str
    sections: list[LessonSection]
    quiz: list[QuizItem]
    exercises: list[str] = field(default_factory=list)
    socratic: list[str] = field(default_factory=list)

    def body_text(self) -> str:
        return "\n\n".join(f"{s.title}\n{s.body}" for s in self.sections)


def parse_lesson(payload: str, corpus_ids: set[str]) -> Lesson:
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        raise LessonParseError("no JSON object in lesson output")
    try:
        obj: Any = json.loads(payload[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise LessonParseError(f"lesson is not valid JSON: {exc}") from exc

    concept = str(obj.get("concept") or "").strip()
    raw_sections = obj.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise LessonParseError("lesson has no sections")
    sections: list[LessonSection] = []
    for i, rs in enumerate(raw_sections):
        if not isinstance(rs, dict) or not str(rs.get("body", "")).strip():
            raise LessonParseError(f"section {i} missing non-empty 'body'")
        cites = [str(c).strip() for c in (rs.get("cites") or []) if str(c).strip()]
        if not cites:
            raise LessonParseError(
                f"section {i} cites nothing — every taught section must ground in the corpus"
            )
        dangling = [c for c in cites if c not in corpus_ids]
        if dangling:
            raise LessonParseError(f"section {i} cites {dangling} — not in the education corpus")
        sections.append(LessonSection(
            title=str(rs.get("title") or f"Section {i + 1}").strip(),
            body=str(rs["body"]).strip(),
            cites=cites,
        ))

    quiz: list[QuizItem] = []
    for i, rq in enumerate(obj.get("quiz") or []):
        if not isinstance(rq, dict):
            raise LessonParseError(f"quiz item {i} must be an object")
        options = [str(o).strip() for o in (rq.get("options") or []) if str(o).strip()]
        if len(options) < 2:
            raise LessonParseError(f"quiz item {i} needs at least two options")
        idx = rq.get("answer_index")
        if not isinstance(idx, int) or not (0 <= idx < len(options)):
            raise LessonParseError(f"quiz item {i} answer_index out of range")
        span = str(rq.get("answer_span") or "").strip()
        if not span:
            raise LessonParseError(f"quiz item {i} missing 'answer_span'")
        quiz.append(QuizItem(
            question=str(rq.get("question") or "").strip(),
            options=options, answer_index=idx, answer_span=span,
        ))
    if not quiz:
        raise LessonParseError("lesson has no quiz — mastery cannot be assessed")

    return Lesson(
        concept=concept,
        sections=sections,
        quiz=quiz,
        exercises=[str(e).strip() for e in (obj.get("exercises") or []) if str(e).strip()][:5],
        socratic=[str(q).strip() for q in (obj.get("socratic") or []) if str(q).strip()][:5],
    )


def unanswerable(lesson: Lesson) -> list[int]:
    """Quiz items whose answer_span does NOT appear in the lesson body —
    the deterministic answerability check (typography-folded, words exact)."""
    body = normalize(lesson.body_text())
    return [
        i for i, item in enumerate(lesson.quiz)
        if normalize(item.answer_span) not in body
    ]


def grade(lesson: Lesson, answers: list[int]) -> dict[str, Any]:
    """Deterministic grading: index-exact, no judgment anywhere."""
    total = len(lesson.quiz)
    padded = list(answers[:total]) + [-1] * (total - len(answers))
    correct = sum(1 for item, a in zip(lesson.quiz, padded) if a == item.answer_index)
    score = correct / total if total else 0.0
    return {
        "correct": correct,
        "total": total,
        "score": round(score, 3),
        "per_question": [
            {"question": item.question, "your_answer": a, "correct_answer": item.answer_index,
             "right": a == item.answer_index, "answer_span": item.answer_span}
            for item, a in zip(lesson.quiz, padded)
        ],
    }


def render_lesson_markdown(lesson: Lesson, roadmap_brief: str | None = None,
                           source_urls: dict[str, str] | None = None) -> str:
    """The lesson as a normal page — same discipline as the research
    renderer: readable first, citations visible, nothing machine-shaped."""
    urls = source_urls or {}
    lines: list[str] = [f"# {lesson.concept}", ""]
    if roadmap_brief:
        lines += ["## Where this sits", "", roadmap_brief, ""]
    for s in lesson.sections:
        marks = "".join(f" [{c}]" for c in s.cites)
        lines += [f"## {s.title}", "", f"{s.body}{marks}", ""]
    if lesson.exercises:
        lines += ["## Try it (proposals — the doing is yours)", ""]
        lines += [f"- {e}" for e in lesson.exercises] + [""]
    if lesson.socratic:
        lines += ["## Think about it (Socratic, unanswered on purpose)", ""]
        lines += [f"- {q}" for q in lesson.socratic] + [""]
    cited = sorted({c for s in lesson.sections for c in s.cites}, key=lambda x: (len(x), x))
    if cited:
        lines += ["## Sources", ""]
        lines += [f"- [{c}] {urls.get(c, 'pinned corpus text')}" for c in cited]
    return "\n".join(lines).strip() + "\n"
