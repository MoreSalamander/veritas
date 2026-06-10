"""The org registry — the catalog of organizations the Hub can host.

P5 proved an organization is `substrate + a cast`. The registry makes that literal:
each entry is a name, a description, and a build function. The Hub picks an org
type per run and never hardcodes a pipeline again. Adding a third org type means
adding one entry here — the engine does not change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from engine.memory import MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome
from orgs.docs_studio.pipeline import build_doc
from orgs.software_studio.pipeline import build_software


@dataclass
class OrgRun:
    """The normalized result of any org's run — what the Hub consumes."""

    org: str
    goal: str
    accepted: bool
    outcomes: list[Outcome]  # in pipeline order; rejected-early runs have fewer
    informed_by: list[str]
    run_id: str
    activity: list[ActivityEntry]


BuildFn = Callable[[str, ModelProvider, MemoryStore], OrgRun]


@dataclass(frozen=True)
class OrgType:
    name: str
    title: str
    description: str  # one plain sentence of purpose
    input_noun: str  # what you give it
    produces: str  # the artifact you get
    verified_by: str  # the gate chain, so the trust story is visible
    goal_hint: str
    build: BuildFn


def _run_software(goal: str, provider: ModelProvider, memory: MemoryStore) -> OrgRun:
    result = build_software(goal, provider, memory)
    outcomes = [result.spec_outcome]
    if result.code_outcome is not None:
        outcomes.append(result.code_outcome)
    return OrgRun(
        org="software",
        goal=goal,
        accepted=result.accepted,
        outcomes=outcomes,
        informed_by=result.informed_by,
        run_id=result.run_id,
        activity=result.activity,
    )


def _run_docs(goal: str, provider: ModelProvider, memory: MemoryStore) -> OrgRun:
    result = build_doc(goal, provider, memory)
    outcomes = [result.outline_outcome]
    if result.doc_outcome is not None:
        outcomes.append(result.doc_outcome)
    return OrgRun(
        org="docs",
        goal=goal,
        accepted=result.accepted,
        outcomes=outcomes,
        informed_by=result.informed_by,
        run_id=result.run_id,
        activity=result.activity,
    )


REGISTRY: dict[str, OrgType] = {
    "software": OrgType(
        name="software",
        title="Software Studio",
        description="Turns a plain-language goal into a working Python function.",
        input_noun="a plain-language goal",
        produces="a verified Python function",
        verified_by="executable spec → syntax → acceptance tests → security scan "
        "→ QA (advisory) → Validation",
        goal_hint="a function that returns the nth Fibonacci number",
        build=_run_software,
    ),
    "docs": OrgType(
        name="docs",
        title="Docs Studio",
        description="Turns a topic into a technical explainer whose code examples actually run.",
        input_noun="a topic",
        produces="a Markdown explainer whose examples run",
        verified_by="usable outline → required sections → every code example executed "
        "→ readability (advisory) → Validation",
        goal_hint="python list comprehensions",
        build=_run_docs,
    ),
}


def get_org(name: str) -> OrgType:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown org type {name!r} (registered: {known})")
    return REGISTRY[name]
