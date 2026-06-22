"""P8 — the Planner (CEO seat): decompose a goal too big for one module into a PLAN.

A plan is a list of module briefs — what modules the app is made of and what each is for.
No code yet; this rung produces and gates the decomposition itself. The Planner decides
WHICH modules exist; the Architect (P6) later decides each module's shape. Two roles, two
levels, each with its own gated artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run


class PlanParseError(ValueError):
    """The proposed plan is not usable. PlanGate rejects on this."""


@dataclass
class ModuleBrief:
    name: str
    goal: str


@dataclass
class AppPlan:
    app_name: str
    modules: list[ModuleBrief]


def _extract_object(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise PlanParseError("no JSON object found")
    return text[start : end + 1]


def parse_plan(payload: str) -> AppPlan:
    try:
        obj: Any = json.loads(_extract_object(payload))
    except (ValueError, TypeError) as exc:
        raise PlanParseError(f"plan is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise PlanParseError("plan must be a JSON object")

    app_name = obj.get("app_name")
    if not isinstance(app_name, str) or not app_name.strip():
        raise PlanParseError("missing app_name")

    raw_modules = obj.get("modules")
    if not isinstance(raw_modules, list) or len(raw_modules) < 2:
        raise PlanParseError("a plan needs at least 2 modules")

    modules: list[ModuleBrief] = []
    seen: set[str] = set()
    for entry in raw_modules:
        if not isinstance(entry, dict):
            raise PlanParseError("each module must be an object")
        name = entry.get("module_name")
        if not isinstance(name, str) or not name.isidentifier():
            raise PlanParseError(f"module_name missing or invalid: {name!r}")
        if name in seen:
            raise PlanParseError(f"duplicate module: {name}")
        seen.add(name)
        goal = entry.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise PlanParseError(f"{name}: missing goal")
        modules.append(ModuleBrief(name=name, goal=goal))

    return AppPlan(app_name=app_name, modules=modules)


PLANNER_SYSTEM = (
    "You are a planner decomposing an app goal into modules. Respond with ONLY a JSON "
    "object — no prose, no fences. Schema: {\"app_name\": <identifier>, \"modules\": "
    "[{\"module_name\": <identifier>, \"goal\": <what this module does>}]}. Provide AT "
    "LEAST 2 cohesive, non-overlapping modules."
)


class PlannerAgent:
    role = "planner"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, goal: str, lessons: str | None = None) -> Artifact:
        prompt = f"App goal: {goal}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=PLANNER_SYSTEM)
        return Artifact.propose(
            type="plan", owner="planner-agent", payload=raw,
            rationale=f"decomposition plan for app goal: {goal}",
        )


class PlanGate(Gate):
    name = "plan"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            plan = parse_plan(artifact.payload)
        except PlanParseError as exc:
            return self._result(False, f"plan not usable: {exc}")
        names = ", ".join(m.name for m in plan.modules)
        return self._result(True, f"{len(plan.modules)} modules: {names}")


@dataclass
class PlanResult:
    plan_outcome: Outcome
    accepted: bool
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build_plan(goal: str, provider: ModelProvider, memory: MemoryStore) -> PlanResult:
    run = Run(goal=goal, memory=memory, max_attempts=provider.retry_budget())
    recalled = memory.recall(goal, categories=["failure", "lesson"], limit=3)
    lessons = format_lessons(recalled)
    informed_by = [record.id for record in recalled]

    plan_artifact = PlannerAgent(provider).propose(goal, lessons=lessons)
    plan_artifact.provenance.informed_by.extend(informed_by)
    plan_outcome = run.submit(plan_artifact, [PlanGate()])
    return PlanResult(plan_outcome, plan_outcome.accepted, informed_by, run.id, list(run.log))
