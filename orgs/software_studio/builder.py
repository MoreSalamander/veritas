"""P7 — one front door for the software org.

`build(goal)` decides the deliverable's shape — a single function or a small module —
and runs the right pipeline. The shape decision is a soft judgment (a router), which is
fine: whatever it picks, the output is still hard-gated. One stable surface for the hub
and for every rung after this to build on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.memory import MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome
from orgs.software_studio.module import build_module
from orgs.software_studio.pipeline import build_software

ROUTER_SYSTEM = (
    "Classify a software goal. Reply with EXACTLY one word: 'module' if it needs several "
    "functions working together, otherwise 'function'. No other text."
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
        return "module" if "module" in raw.strip().lower() else "function"


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
    chosen = shape if shape in ("function", "module") else Router(provider).classify(goal)

    if chosen == "module":
        m = build_module(goal, provider, memory)
        outcomes = [m.contract_outcome]
        if m.integration_outcome is not None:
            outcomes.append(m.integration_outcome)
        if m.code_outcome is not None:
            outcomes.append(m.code_outcome)
        return BuildResult("module", m.accepted, outcomes, m.informed_by, m.run_id, m.activity)

    s = build_software(goal, provider, memory, document=True)
    outcomes = [s.spec_outcome]
    if s.code_outcome is not None:
        outcomes.append(s.code_outcome)
    if s.doc_outcome is not None:
        outcomes.append(s.doc_outcome)
    return BuildResult("function", s.accepted, outcomes, s.informed_by, s.run_id, s.activity)
