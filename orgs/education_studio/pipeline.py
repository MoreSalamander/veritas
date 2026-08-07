"""The university run: goal -> roadmap -> research -> lesson -> assessment.

Same spine as every org — agents propose, deterministic contracts and
gates decide, memory learns — with the learner model as the new organ:
per-tenant, earned only by graded assessment, consulted before anything
is planned or taught.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.memory import MemoryRecord, MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.education_studio.curriculum import (
    EDU_ANGLES,
    MASTERY_THRESHOLD,
    LearnerModel,
    LearningRoadmap,
    RoadmapParseError,
    parse_roadmap,
)
from orgs.education_studio.lesson import (
    Lesson,
    LessonParseError,
    grade,
    parse_lesson,
    unanswerable,
)
from orgs.research_studio.intelligence import AcquiredSource, fan_out

if TYPE_CHECKING:
    from commons.parallel_client import SearchClient


CURRICULUM_SYSTEM = (
    "You are a curriculum planner. Given a learning goal and the learner "
    "model, produce ONLY a JSON object: "
    '{"concepts": [{"name": <concept>, "summary": <one line>}], '
    '"edges": [{"source": <concept>, "relation": <one of: requires, '
    "builds_upon, related_to, applied_in, contrasts_with>, "
    '"target": <concept>}]}. '
    "6-16 concepts, from true prerequisites to the goal itself. Every edge "
    "endpoint must appear in concepts; prerequisite edges (requires/"
    "builds_upon) must form a DAG — a machine computes the ordering and a "
    "cycle refuses the whole plan. Do NOT include concepts the learner "
    "model marks mastered unless they are genuinely needed as review."
)

TEACHER_SYSTEM = (
    "You are a teacher writing one grounded lesson. You are given the "
    "concept, the roadmap context, the learner model, and an education "
    "corpus of SOURCES with ids. Produce ONLY a JSON object: "
    '{"concept": <name>, "sections": [{"title", "body", "cites": [<source '
    "ids backing this section>]}], "
    '"quiz": [{"question", "options": [<3-4>], "answer_index": <int>, '
    '"answer_span": <a short phrase FROM YOUR OWN SECTIONS that contains '
    "the answer>}], "
    '"exercises": [<things to actually do>], "socratic": [<questions you '
    "deliberately leave unanswered>]}. "
    "Rules a machine checks: every section cites at least one REAL corpus "
    "id; every quiz answer_span must appear verbatim in your own sections "
    "(a quiz the lesson can't answer is refused); 3-6 sections, 3-5 quiz "
    "items. Teach for understanding: build from what the learner knows, "
    "name the one idea each section exists to land."
)


class CurriculumAgent:
    role = "researcher"  # the planner hat of the education cast

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, goal: str, learner: LearnerModel, feedback: str | None = None) -> str:
        prompt = f"{learner.briefing()}\n\nLearning goal: {goal}"
        if feedback:
            prompt = f"Your previous roadmap was REJECTED: {feedback}\nFix exactly that.\n\n{prompt}"
        return self.provider.propose(role=self.role, prompt=prompt, system=CURRICULUM_SYSTEM)


class TeacherAgent:
    role = "researcher"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(
        self, concept: str, roadmap_brief: str, learner: LearnerModel,
        corpus_text: str, lessons: str | None = None, feedback: str | None = None,
    ) -> Artifact:
        prompt = (
            f"{learner.briefing()}\n\n{roadmap_brief}\n\n"
            f"Concept to teach NOW: {concept}\n\nEDUCATION CORPUS:\n{corpus_text}"
        )
        if feedback:
            prompt = f"Your previous lesson was REJECTED: {feedback}\nFix exactly that.\n\n{prompt}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=TEACHER_SYSTEM)
        return Artifact.propose(
            type="lesson", owner="teacher-agent", payload=raw,
            rationale=f"grounded lesson on: {concept}",
            model=getattr(self.provider, "model", None),
        )


class LessonContractGate(Gate):
    """HARD: the lesson parses, every section grounds in the corpus, and
    every quiz item is answerable from the lesson itself."""

    name = "lesson-contract"
    determinism = Determinism.HARD

    def __init__(self, corpus_ids: set[str]) -> None:
        self.corpus_ids = corpus_ids

    def check(self, artifact: Artifact) -> GateResult:
        try:
            lesson = parse_lesson(artifact.payload, self.corpus_ids)
        except LessonParseError as exc:
            return self._result(False, f"lesson not usable: {exc}")
        bad = unanswerable(lesson)
        if bad:
            spans = "; ".join(lesson.quiz[i].answer_span[:60] for i in bad)
            return self._result(
                False,
                f"quiz item(s) {bad} unanswerable from the lesson taught — "
                f"the span(s) {spans!r} do not appear in the sections",
            )
        return self._result(
            True,
            f"{len(lesson.sections)} grounded section(s), {len(lesson.quiz)} answerable quiz item(s)",
        )


class LearnerStore:
    """The learner model in tenant memory: read the earned state, write
    only what grading proves."""

    RECORD_TITLE = "learner-model"

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    def load(self) -> LearnerModel:
        # Every save persists a fresh record; the model is the NEWEST one —
        # last-write-wins by created_at, deterministically.
        newest = None
        for record in self.memory.load_all():
            if record.category == "learner" and record.title == self.RECORD_TITLE:
                if newest is None or record.created_at > newest.created_at:
                    newest = record
        if newest is None:
            return LearnerModel()
        try:
            data = json.loads(newest.body)
            return LearnerModel(
                known={str(k): float(v) for k, v in (data.get("known") or {}).items()},
                weak=[str(w) for w in data.get("weak") or []],
                goals=[str(g) for g in data.get("goals") or []],
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            return LearnerModel()

    def save(self, model: LearnerModel) -> None:
        self.memory.persist(MemoryRecord(
            category="learner", title=self.RECORD_TITLE,
            body=json.dumps({"known": model.known, "weak": model.weak, "goals": model.goals}),
            tags=["education-kg"],
            provenance={"updated_by": "graded assessment only"},
        ))


@dataclass
class LearningResult:
    goal: str
    roadmap: LearningRoadmap
    concept: str
    lesson_outcome: Outcome
    lesson: Lesson | None
    sources: list[AcquiredSource]
    accepted: bool
    learner: LearnerModel
    run_id: str
    activity: list[ActivityEntry] = field(default_factory=list)
    context_graph: dict = field(default_factory=dict)


def build_learning(
    goal: str,
    provider: ModelProvider,
    memory: MemoryStore,
    search_client: "SearchClient",
    *,
    per_angle: int = 2,
) -> LearningResult:
    """One session of the university: consult the learner model, verify the
    roadmap, research the next concept in parallel, teach it grounded, and
    hand back an assessable lesson. Mastery moves ONLY via record_grade."""
    store = LearnerStore(memory)
    learner = store.load()
    if goal not in learner.goals:
        learner.goals.append(goal)

    planner = CurriculumAgent(provider)
    raw = planner.propose(goal, learner)
    try:
        roadmap = parse_roadmap(raw, goal, learner)
    except RoadmapParseError as exc:
        raw = planner.propose(goal, learner, feedback=str(exc))
        roadmap = parse_roadmap(raw, goal, learner)  # second failure raises — honest

    concept = roadmap.path[0]
    queries = {a: f"{concept} {bias}" for a, (bias, _c) in EDU_ANGLES.items()}
    sources = fan_out(queries, search_client, objective=f"learn {concept} (goal: {goal})",
                      per_angle=per_angle)
    corpus_ids = {f"src{i + 1}" for i in range(len(sources))}
    corpus_text = "\n\n".join(
        f"source id: src{i + 1}\n{s.corpus_entry()[:1600]}" for i, s in enumerate(sources)
    ) or "source id: none\n(no live corpus reachable — refuse to invent citations)"

    run = Run(goal=f"{goal} :: {concept}", memory=memory)
    recalled = memory.recall(concept, categories=["failure", "lesson", "decision"], limit=3)
    lessons_text = format_lessons(recalled)

    def propose(feedback: str | None) -> Artifact:
        return TeacherAgent(provider).propose(
            concept, roadmap.brief(), learner, corpus_text,
            lessons=lessons_text, feedback=feedback,
        )

    outcome = run.attempt(propose, [LessonContractGate(corpus_ids), ValidationGate()])

    lesson: Lesson | None = None
    if outcome.artifact is not None:
        try:
            lesson = parse_lesson(outcome.artifact.payload, corpus_ids)
        except LessonParseError:
            lesson = None

    context_graph = {
        "goal": goal,
        "concept": concept,
        "path": roadmap.path,
        "skipped_as_mastered": roadmap.skipped,
        "weak": learner.weak,
        "edges": [
            {"source": e.source, "relation": e.relation, "target": e.target}
            for e in roadmap.edges
        ],
    }

    if outcome.accepted:
        store.save(learner)  # goals recorded; mastery still untouched here
        existing = {r.title for r in memory.load_all() if r.category == "entity"}
        for name, summary in roadmap.concepts.items():
            title = f"concept:{name}"
            if title in existing:
                continue
            memory.persist(MemoryRecord(
                category="entity", title=title,
                body=json.dumps({"concept": name, "summary": summary, "goal": goal}),
                tags=["education-kg", "concept"], provenance={"goal": goal},
            ))
        for e in roadmap.edges:
            memory.persist(MemoryRecord(
                category="relationship",
                title=f"{e.source} {e.relation} {e.target}",
                body=json.dumps({"source": e.source, "relation": e.relation, "target": e.target}),
                tags=["education-kg", e.relation], provenance={"goal": goal},
            ))

    return LearningResult(
        goal=goal, roadmap=roadmap, concept=concept, lesson_outcome=outcome,
        lesson=lesson, sources=list(sources), accepted=outcome.accepted,
        learner=learner, run_id=run.id, activity=list(run.log),
        context_graph=context_graph,
    )


def record_grade(memory: MemoryStore, concept: str, lesson: Lesson, answers: list[int]) -> dict[str, Any]:
    """Deterministic assessment: grade, then move the learner model — the
    ONLY door mastery can enter through."""
    result = grade(lesson, answers)
    store = LearnerStore(memory)
    model = store.load()
    prior = model.known.get(concept, 0.0)
    model.known[concept] = max(prior, result["score"])
    if result["score"] >= MASTERY_THRESHOLD:
        model.weak = [w for w in model.weak if w != concept]
        result["mastered"] = True
    else:
        if concept not in model.weak:
            model.weak.append(concept)
        result["mastered"] = False
    store.save(model)
    result["concept"] = concept
    result["mastery_threshold"] = MASTERY_THRESHOLD
    return result
