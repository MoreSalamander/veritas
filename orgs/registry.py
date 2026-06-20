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
from typing import Any

from engine.memory import MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome
from orgs.production_studio.pipeline import build_production
from orgs.production_studio.roster import roster as production_roster
from orgs.research_studio.pipeline import build_report
from orgs.research_studio.roster import roster as research_roster
from orgs.software_studio.builder import build
from orgs.software_studio.roster import roster as software_roster
from orgs.web_studio.pipeline import build_page
from orgs.web_studio.roster import roster as web_roster


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


# Most orgs build from just a goal; some (Research) also take a pinned source corpus. `sources`
# is optional and ignored by orgs that don't need it — the dispatch stays uniform.
BuildFn = Callable[..., OrgRun]


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
    roster: Callable[[], dict[str, Any]] | None = None  # cast + gates, for the Org view
    needs_sources: bool = False  # the UI shows a sources box for these orgs


def _run_software(
    goal: str, provider: ModelProvider, memory: MemoryStore, sources: list[str] | None = None
) -> OrgRun:
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


def _run_web(
    goal: str, provider: ModelProvider, memory: MemoryStore, sources: list[str] | None = None
) -> OrgRun:
    result = build_page(goal, provider, memory)
    outcomes = [result.spec_outcome]
    if result.page_outcome is not None:
        outcomes.append(result.page_outcome)
    return OrgRun(
        org="web",
        goal=goal,
        accepted=result.accepted,
        outcomes=outcomes,
        informed_by=result.informed_by,
        run_id=result.run_id,
        activity=result.activity,
    )


def _run_research(
    goal: str, provider: ModelProvider, memory: MemoryStore, sources: list[str] | None = None
) -> OrgRun:
    # The pasted sources become a pinned corpus (src1, src2, ...); the report cites into it.
    corpus = {f"src{i + 1}": s for i, s in enumerate(sources or []) if s.strip()}
    result = build_report(goal, corpus, provider, memory)
    return OrgRun(
        org="research",
        goal=goal,
        accepted=result.accepted,
        outcomes=[result.report_outcome],
        informed_by=result.informed_by,
        run_id=result.run_id,
        activity=result.activity,
    )


def _run_production(
    goal: str, provider: ModelProvider, memory: MemoryStore, sources: list[str] | None = None
) -> OrgRun:
    result = build_production(goal, provider, memory)
    return OrgRun(
        org="production",
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
        roster=software_roster,
    ),
    "web": OrgType(
        name="web",
        title="Web Studio",
        description="Turns a goal into a working web page — a single self-contained HTML "
        "document, verified by rendering it in a real browser.",
        input_noun="a UI goal",
        produces="a verified HTML page (renders clean, fits the viewport, accessible)",
        verified_by="rendered in a real headless browser: loads with no console errors, no "
        "layout overflow, the required elements present, and accessibility basics hold",
        goal_hint="a landing page for a coffee shop",
        build=_run_web,
        roster=web_roster,
    ),
    "research": OrgType(
        name="research",
        title="Research Studio",
        description="Turns a question + sources into a grounded report — a set of claims, each "
        "cited to and quoted verbatim from the sources you provide. Verified by grounding, not "
        "by good writing.",
        input_noun="a question and a set of sources",
        produces="a grounded report (every claim cited, every quote verbatim)",
        verified_by="every claim is attributed, every citation resolves to a provided source, "
        "every quoted span appears verbatim in it; whether the source supports the claim is "
        "judged (soft)",
        goal_hint="how fast can bald eagles fly, and how big are their nests?",
        build=_run_research,
        roster=research_roster,
        needs_sources=True,
    ),
    "production": OrgType(
        name="production",
        title="Production Studio",
        description="Turns a brief into a verified production chain — concept, then script, then "
        "storyboard — for a short narrated video. Verified by consistency, not by good taste.",
        input_noun="a production brief",
        produces="a concept + script + storyboard whose every stage traces to the last",
        verified_by="the concept declares the entities; the script may use only those; the "
        "storyboard covers every beat and shows only what the beat contains — referential "
        "integrity end to end (whether it's compelling is the human tier)",
        goal_hint="a 60-second explainer on why the sky is blue, for curious kids",
        build=_run_production,
        roster=production_roster,
    ),
}


def get_org(name: str) -> OrgType:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown org type {name!r} (registered: {known})")
    return REGISTRY[name]
