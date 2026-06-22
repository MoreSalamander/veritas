"""Cross-org planning — the conversational layer that spans the whole registry.

This is NOT a new organization: it has no verification model of its own. It ORCHESTRATES.
A planner proposes an ordered list of `{org, goal}` steps; a deterministic gate checks the plan
is *runnable* (every step names a real studio with a concrete goal); then each step runs through
ITS org's existing gates. The plan ships iff every step ships.

It generalizes three things Veritas already had:
  - the router (intent -> one {org, goal}) is the 1-step case of a plan,
  - the interview (converse -> a gateable spec) is this same move for ONE org,
  - the presets (startup = web+software) are *frozen* plans this lets the planner derive.

The discipline holds exactly as in the interview: the model PROPOSES the plan, but a
deterministic check — not the model — decides whether it's runnable. A plan the model calls
"done" that names a studio we don't have, or a step with no goal, is sent back, not run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.memory import MemoryStore
from engine.model import ModelProvider
from orgs.registry import REGISTRY, OrgRun, get_org

# The planner composes from the five verification-model ENGINES. The presets are themselves
# frozen plans (startup = web+software), so letting the planner pick one as a step would be
# composing a composition — muddy. We steer the model toward the engines; the gate still accepts
# any *registered* org (it checks runnability, not taste), so a preset step isn't an error.
ENGINE_ORGS = ("software", "web", "research", "production", "empirical")


class PlanParseError(ValueError):
    """The proposed plan is not usable JSON. The scorer rejects on this."""


@dataclass
class PlanStep:
    org: str
    goal: str


@dataclass
class Plan:
    request: str
    steps: list[PlanStep] = field(default_factory=list)


def _extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise PlanParseError("no JSON object found")
    try:
        obj: Any = json.loads(text[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise PlanParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise PlanParseError("not a JSON object")
    return obj


def parse_plan(request: str, payload: str) -> Plan:
    obj = _extract_json(payload)
    raw_steps = obj.get("steps", [])
    steps: list[PlanStep] = []
    if isinstance(raw_steps, list):
        for s in raw_steps:
            if isinstance(s, dict):
                steps.append(PlanStep(org=str(s.get("org", "")).strip(),
                                      goal=str(s.get("goal", "")).strip()))
    return Plan(request=request, steps=steps)


def plan_problems(plan: Plan) -> list[str]:
    """The deterministic 'score' the planner drives toward: the reasons a plan ISN'T runnable.
    Empty list == runnable (every step names a registered studio and carries a concrete goal)."""
    problems: list[str] = []
    if not plan.steps:
        problems.append("the plan has no steps")
    for i, s in enumerate(plan.steps, start=1):
        if not s.org:
            problems.append(f"step {i}: no studio named")
        elif s.org not in REGISTRY:
            problems.append(f"step {i}: unknown studio {s.org!r} (have: {', '.join(ENGINE_ORGS)})")
        if not s.goal:
            problems.append(f"step {i}: empty goal")
    return problems


class PlanScorerGate(Gate):
    """HARD: the plan parses and is runnable — otherwise there is nothing to execute. The
    cross-org analogue of the software org's spec-scorer and the interview's create-spec gate."""

    name = "plan-runnable"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            plan = parse_plan("", artifact.payload)
        except PlanParseError as exc:
            return self._result(False, f"plan not usable: {exc}")
        problems = plan_problems(plan)
        if problems:
            return self._result(False, "plan not runnable yet — " + "; ".join(problems))
        chain = " -> ".join(f"{s.org}" for s in plan.steps)
        return self._result(True, f"runnable: {len(plan.steps)} step(s) [{chain}]")


def _planner_system() -> str:
    studios = "; ".join(
        f"{name} = {REGISTRY[name].produces}" for name in ENGINE_ORGS if name in REGISTRY
    )
    return (
        "You are a planner. Break the user's request into an ordered list of steps, where each "
        "step is ONE studio doing ONE concrete thing. Use ONLY these studios: " + studios + ". "
        "Order matters: earlier steps inform later ones (e.g. research the facts, then build the "
        "page that uses them). Keep it minimal — only the steps the request actually needs; a "
        "simple request may be a single step. Each goal must be concrete enough for that studio to "
        "act on. Respond with ONLY JSON, no prose: "
        "{\"steps\": [{\"org\": \"<studio>\", \"goal\": \"<concrete goal>\"}, ...]}."
    )


_FIX_PLAN = (
    "That plan is not runnable. Output a corrected plan JSON now, fixing exactly these problems "
    "and using only the listed studios:"
)


class PlannerAgent:
    role = "planner"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, request: str, feedback: str | None = None) -> str:
        prompt = f"Request: {request}"
        if feedback:
            prompt += f"\n\n{feedback}"
        return self.provider.propose(role=self.role, prompt=prompt, system=_planner_system())


def propose_plan(request: str, provider: ModelProvider, *, max_attempts: int = 3) -> Plan:
    """Propose a runnable plan, self-correcting against the deterministic gate. Mirrors the
    interview's discipline: the model proposes, `plan_problems` decides if it's runnable, and a
    non-runnable plan is re-proposed with the exact problems as feedback — up to max_attempts."""
    agent = PlannerAgent(provider)
    feedback: str | None = None
    last: Plan = Plan(request=request, steps=[])
    for _ in range(max_attempts):
        try:
            raw = agent.propose(request, feedback)
            last = parse_plan(request, raw)
        except PlanParseError:
            feedback = "Your last reply was not valid JSON. Respond with ONLY the plan JSON object."
            continue
        problems = plan_problems(last)
        if not problems:
            return last
        feedback = f"{_FIX_PLAN} {'; '.join(problems)}"
    return last  # may still be non-runnable; the caller gates it before executing


@dataclass
class StepResult:
    org: str
    goal: str
    run: OrgRun

    @property
    def accepted(self) -> bool:
        return self.run.accepted


@dataclass
class PlanResult:
    plan: Plan
    step_results: list[StepResult]
    accepted: bool  # every step shipped (a strict chain: a failed step stops the rest)
    problems: list[str] = field(default_factory=list)  # set when the plan itself wasn't runnable


def execute_plan(
    plan: Plan,
    provider: ModelProvider,
    memory_for: Callable[[str], MemoryStore],
    *,
    sources: list[str] | None = None,
    on_step: Callable[[int, StepResult], None] | None = None,
) -> PlanResult:
    """Run each step through its org's own pipeline, in order, STRICT: a step that doesn't ship
    stops the plan (matching how every other multi-stage chain in Veritas behaves). Each step uses
    its org's own memory namespace (recall stays domain-relevant). `on_step(index, result)` is an
    optional hook for live streaming. The plan ships iff every step ships.

    Note: cross-step data handoff is deliberately NOT typed here — each step gets the original
    goal text only. Threading one step's output into the next is the next rung; this slice proves
    the orchestration + gating end to end first."""
    problems = plan_problems(plan)
    if problems:
        return PlanResult(plan, [], accepted=False, problems=problems)

    results: list[StepResult] = []
    accepted = True
    for i, step in enumerate(plan.steps):
        org = get_org(step.org)
        run = org.build(step.goal, provider, memory_for(step.org), sources=sources)
        sr = StepResult(org=step.org, goal=step.goal, run=run)
        results.append(sr)
        if on_step is not None:
            on_step(i, sr)
        if not run.accepted:
            accepted = False
            break  # strict chain — don't run later steps on a broken foundation
    return PlanResult(plan, results, accepted=accepted)


def gate_plan(plan: Plan) -> tuple[bool, str]:
    """Check the plan against the HARD PlanScorerGate (the same authority execute_plan uses) and
    return (runnable, evidence) for the UI's trust report — so a plan is shown as *gated*, not
    merely parsed. Pure: calls the gate directly, no memory side effects."""
    artifact = Artifact.propose(
        type="plan", owner="planner", payload=json.dumps({"steps": [
            {"org": s.org, "goal": s.goal} for s in plan.steps]}),
        rationale=f"cross-org plan for: {plan.request}",
    )
    result = PlanScorerGate().check(artifact)
    return result.passed, result.evidence
