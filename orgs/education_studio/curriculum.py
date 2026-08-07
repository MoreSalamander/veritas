"""The curriculum contracts: a roadmap is a verified graph, not a syllabus.

Three deterministic rules make the difference between "an AI made me a
study plan" and a plan that can be trusted:

* **Closed relation vocabulary** — prerequisite structure uses typed edges
  (requires / builds_upon / related_to / applied_in / contrasts_with);
  an invented relation is parse-refused.
* **DAG or refusal** — a curriculum with a prerequisite cycle is not a
  curriculum; topological order is computed, and a cycle refuses the plan.
* **Personalization is subtraction, not vibes** — concepts the learner has
  already proven are removed from the path deterministically, and the cut
  is SHOWN ("skipping N you've mastered"), never silent.

The learner model lives in tenant memory: what is known (with mastery
scores), what is weak, what the goals are. It is updated only by graded
assessment — never by the model's opinion of the learner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

EDU_RELATIONS = ("requires", "builds_upon", "related_to", "applied_in", "contrasts_with")

# The education research angles: query bias + charter, over the shared fan-out.
EDU_ANGLES: dict[str, tuple[str, str]] = {
    "academic": ("university course lecture notes textbook", "The rigorous record: courses, texts, papers."),
    "explanations": ("intuitive explanation analogy beginner guide", "The clearest ways anyone has said it."),
    "practical": ("hands-on project exercise tutorial build", "Where the concept becomes something you do."),
    "history": ("history origin who discovered development of", "Where the idea came from and why."),
    "industry": ("used in industry real world application career", "What it's for outside the classroom."),
}

MASTERY_THRESHOLD = 0.8  # a stated policy: quiz score at/above this marks the concept mastered


class RoadmapParseError(ValueError):
    """The proposed roadmap is not usable as a curriculum."""


@dataclass
class LearnerModel:
    """What the org knows about this learner — earned, not assumed."""

    known: dict[str, float] = field(default_factory=dict)   # concept -> best graded score
    weak: list[str] = field(default_factory=list)           # attempted, below threshold
    goals: list[str] = field(default_factory=list)

    def mastered(self) -> set[str]:
        return {c for c, score in self.known.items() if score >= MASTERY_THRESHOLD}

    def briefing(self) -> str:
        if not self.known and not self.weak:
            return "LEARNER MODEL: new learner — nothing proven yet, assume the goal's stated level."
        lines = ["LEARNER MODEL (earned by graded assessment, not assumption):"]
        if self.mastered():
            lines.append("- mastered: " + ", ".join(sorted(self.mastered())))
        if self.weak:
            lines.append("- weak (attempted, below threshold): " + ", ".join(sorted(set(self.weak))))
        if self.goals:
            lines.append("- goals: " + "; ".join(self.goals[-3:]))
        return "\n".join(lines)


@dataclass
class RoadmapEdge:
    source: str
    relation: str
    target: str


@dataclass
class LearningRoadmap:
    """The verified curriculum graph plus the learner's personalized path."""

    goal: str
    concepts: dict[str, str]                 # name -> one-line summary
    edges: list[RoadmapEdge]
    order: list[str]                         # full topological order
    path: list[str]                          # order minus mastered concepts
    skipped: list[str]                       # what personalization removed, shown honestly

    def brief(self) -> str:
        lines = [f"LEARNING ROADMAP — {self.goal}", f"- concepts: {len(self.concepts)}"]
        for name in self.order:
            prereqs = [e.source for e in self.edges if e.target == name and e.relation in ("requires", "builds_upon")]
            mark = " (mastered — skipped)" if name in self.skipped else ""
            req = f"  ← {', '.join(prereqs)}" if prereqs else ""
            lines.append(f"- {name}{mark}: {self.concepts[name]}{req}")
        if self.skipped:
            lines.append(f"- personalization: skipping {len(self.skipped)} concept(s) you've already proven")
        return "\n".join(lines)


def _toposort(names: list[str], edges: list[RoadmapEdge]) -> list[str]:
    """Prerequisite-respecting order; raises on a cycle — a curriculum that
    requires itself is refused, not repaired."""
    hard = [(e.source, e.target) for e in edges if e.relation in ("requires", "builds_upon")]
    incoming: dict[str, set[str]] = {n: set() for n in names}
    for src, tgt in hard:
        incoming[tgt].add(src)
    order: list[str] = []
    ready = sorted(n for n, deps in incoming.items() if not deps)
    while ready:
        node = ready.pop(0)
        order.append(node)
        for n in sorted(incoming):
            if node in incoming[n]:
                incoming[n].discard(node)
                if not incoming[n] and n not in order and n not in ready:
                    ready.append(n)
        ready.sort()
    if len(order) != len(names):
        stuck = sorted(set(names) - set(order))
        raise RoadmapParseError(f"prerequisite cycle involving {stuck} — a curriculum cannot require itself")
    return order


def parse_roadmap(payload: str, goal: str, learner: LearnerModel) -> LearningRoadmap:
    """The deterministic contract on the Curriculum Planner's proposal."""
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        raise RoadmapParseError("no JSON object in roadmap output")
    try:
        obj: Any = json.loads(payload[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise RoadmapParseError(f"roadmap is not valid JSON: {exc}") from exc

    raw_concepts = obj.get("concepts")
    if not isinstance(raw_concepts, list) or not raw_concepts:
        raise RoadmapParseError("roadmap names no concepts")
    concepts: dict[str, str] = {}
    for i, rc in enumerate(raw_concepts):
        if not isinstance(rc, dict) or not str(rc.get("name", "")).strip():
            raise RoadmapParseError(f"concept {i} missing 'name'")
        concepts[str(rc["name"]).strip()] = str(rc.get("summary") or "").strip()
    if len(concepts) > 24:
        raise RoadmapParseError("roadmap too large — a 24-concept ceiling keeps paths walkable")

    edges: list[RoadmapEdge] = []
    for i, re_ in enumerate(obj.get("edges") or []):
        if not isinstance(re_, dict):
            raise RoadmapParseError(f"edge {i} must be an object")
        src, rel, tgt = str(re_.get("source", "")).strip(), re_.get("relation"), str(re_.get("target", "")).strip()
        if rel not in EDU_RELATIONS:
            raise RoadmapParseError(f"edge {i} relation {rel!r} not in {EDU_RELATIONS}")
        if src not in concepts or tgt not in concepts:
            raise RoadmapParseError(f"edge {i} references an undeclared concept — every endpoint must be in 'concepts'")
        if src == tgt:
            raise RoadmapParseError(f"edge {i}: a concept cannot require itself")
        edges.append(RoadmapEdge(source=src, relation=str(rel), target=tgt))

    order = _toposort(list(concepts), edges)
    mastered = learner.mastered()
    path = [c for c in order if c not in mastered]
    skipped = [c for c in order if c in mastered]
    if not path:
        raise RoadmapParseError(
            "every concept in this roadmap is already mastered — the goal needs to go further"
        )
    return LearningRoadmap(
        goal=goal, concepts=concepts, edges=edges, order=order, path=path, skipped=skipped,
    )
