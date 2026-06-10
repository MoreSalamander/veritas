"""The org registry — the catalog of organizations the Hub can host.

An organization is `substrate + a cast`, and what makes one a SEPARATE org (rather
than a role inside an existing one) is its VERIFICATION MODEL — its way of knowing an
artifact is trustworthy. Same verification model → same org, different role. Different
verification model → different org. (Documenting code is verified by executing code,
so it's a role in the software org, not a peer — see DocAgent.) A genuinely separate
org belongs here only when "done" means something different: e.g. a research org
verified by source-grounding, a production org verified by format/integrity.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from engine.memory import MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome
from orgs.software_studio.builder import build


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
    result = build(goal, provider, memory)  # routes to a function or a module build
    return OrgRun(
        org="software",
        goal=goal,
        accepted=result.accepted,
        outcomes=result.outcomes,
        informed_by=result.informed_by,
        run_id=result.run_id,
        activity=result.activity,
    )


REGISTRY: dict[str, OrgType] = {
    "software": OrgType(
        name="software",
        title="Software Studio",
        description="Turns a goal into working Python — picking the shape automatically: a "
        "single function, a small module, or a runnable multi-module app.",
        input_noun="a software goal",
        produces="verified Python (a function, a module, or a runnable app)",
        verified_by="every artifact gated (spec/contract/code/security/validation); a module "
        "must pass its integration test, an app must pass an end-to-end test that runs it",
        goal_hint="a function that returns the nth Fibonacci number",
        build=_run_software,
    ),
}


def get_org(name: str) -> OrgType:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown org type {name!r} (registered: {known})")
    return REGISTRY[name]
