"""P7 — one front door for the software org.

`build(goal)` decides the deliverable's shape — a single function or a small module —
and runs the right pipeline. The shape decision is a soft judgment (a router), which is
fine: whatever it picks, the output is still hard-gated. One stable surface for the hub
and for every rung after this to build on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.memory import MemoryRecord, MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome
from orgs.software_studio.app import build_app
from orgs.software_studio.module import build_module
from orgs.software_studio.pipeline import build_software

ROUTER_SYSTEM = (
    "Classify a software goal by how much work it is, IGNORING words like 'app', 'program', "
    "or 'tool'. Reply with EXACTLY one word: 'function' for a single calculation or operation "
    "(e.g. convert a temperature, reverse a string, check if prime); 'module' for a few "
    "closely-related functions (e.g. a pair of converters, a small calculator); 'app' ONLY for "
    "multiple genuinely-independent components working together (e.g. storage + commands + "
    "display). When unsure, pick the SMALLER shape. No other text."
)


class Router:
    role = "router"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def classify(self, goal: str) -> str:
        # Soft pre-decision; default to the simpler shape if anything goes wrong.
        try:
            raw = self.provider.propose(role=self.role, prompt=f"Goal: {goal}", system=ROUTER_SYSTEM)
        except Exception:
            return "function"
        text = raw.strip().lower()
        if "app" in text:
            return "app"
        if "module" in text:
            return "module"
        return "function"


@dataclass
class BuildResult:
    shape: str  # "function" | "module"
    accepted: bool
    outcomes: list[Outcome]
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build(
    goal: str, provider: ModelProvider, memory: MemoryStore, *, shape: str = "auto"
) -> BuildResult:
    chosen = shape if shape in ("function", "module", "app") else Router(provider).classify(goal)

    if chosen == "app":
        a = build_app(goal, provider, memory)
        outcomes = [a.plan_outcome]
        for o in (a.package_outcome, a.entrypoint_outcome, a.e2e_outcome):
            if o is not None:
                outcomes.append(o)
        result = BuildResult("app", a.accepted, outcomes, a.informed_by, a.run_id, a.activity)
    elif chosen == "module":
        m = build_module(goal, provider, memory)
        outcomes = [m.contract_outcome]
        if m.integration_outcome is not None:
            outcomes.append(m.integration_outcome)
        if m.code_outcome is not None:
            outcomes.append(m.code_outcome)
        result = BuildResult("module", m.accepted, outcomes, m.informed_by, m.run_id, m.activity)
    else:
        s = build_software(goal, provider, memory, document=True)
        outcomes = [s.spec_outcome]
        if s.code_outcome is not None:
            outcomes.append(s.code_outcome)
        if s.doc_outcome is not None:
            outcomes.append(s.doc_outcome)
        result = BuildResult("function", s.accepted, outcomes, s.informed_by, s.run_id, s.activity)

    # MEMORY seat: record what was decided, on acceptance, so related future builds recall it.
    if result.accepted:
        memory.persist(
            MemoryRecord.from_decision(
                goal=goal,
                shape=result.shape,
                artifact_types=[o.artifact.type for o in result.outcomes],
                source_ids=[o.artifact.id for o in result.outcomes],
            )
        )
    return result
