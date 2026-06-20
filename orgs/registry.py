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

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from engine.memory import MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome
from orgs.empirical_lab.pipeline import build_experiment
from orgs.empirical_lab.roster import roster as empirical_roster
from orgs.presets import (
    build_article,
    build_game,
    build_lesson,
    build_startup,
)
from orgs.production_studio.assets import AssetGenerator, SayGenerator, StubGenerator
from orgs.production_studio.pipeline import build_production
from orgs.production_studio.publishing import FfmpegPublisher, Publisher
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
    # Run the full chain: stub assets always, and a real ffmpeg publish when ffmpeg is available
    # (else the chain stops at the timeline — still verified, just unrendered). Assets + the output
    # land under <data>/productions/<id>/ so the Hub can serve and play the result.
    data_root = memory.base.parent.parent  # <data>/memory/production -> <data>
    work = data_root / "productions" / uuid4().hex
    publisher: Publisher | None = (
        FfmpegPublisher() if shutil.which("ffmpeg") and shutil.which("ffprobe") else None
    )
    # Real spoken narration via macOS `say` when available; silent placeholder otherwise. (Visuals
    # stay placeholder until an image engine is wired behind the same seam.)
    generator: AssetGenerator = SayGenerator() if shutil.which("say") else StubGenerator()
    result = build_production(
        goal, provider, memory,
        asset_generator=generator, asset_dir=work, publisher=publisher,
    )
    return OrgRun(
        org="production",
        goal=goal,
        accepted=result.accepted,
        outcomes=result.outcomes,
        informed_by=result.informed_by,
        run_id=result.run_id,
        activity=result.activity,
    )


def _run_empirical(
    goal: str, provider: ModelProvider, memory: MemoryStore, sources: list[str] | None = None
) -> OrgRun:
    result = build_experiment(goal, provider, memory)
    return OrgRun(
        org="empirical",
        goal=goal,
        accepted=result.accepted,
        outcomes=result.outcomes,
        informed_by=result.informed_by,
        run_id=result.run_id,
        activity=result.activity,
    )


def _run_grounded_preset(
    build_fn: Callable[..., Any], name: str, goal: str, provider: ModelProvider,
    memory: MemoryStore, sources: list[str] | None,
) -> OrgRun:
    corpus = {f"src{i + 1}": s for i, s in enumerate(sources or []) if s.strip()}
    result = build_fn(goal, corpus, provider, memory)
    return OrgRun(name, goal, result.accepted, [result.report_outcome],
                  result.informed_by, result.run_id, result.activity)


def _run_composition(
    build_fn: Callable[..., Any], name: str, goal: str, provider: ModelProvider,
    memory: MemoryStore, sources: list[str] | None = None,
) -> OrgRun:
    result = build_fn(goal, provider, memory)
    return OrgRun(name, goal, result.accepted, result.outcomes,
                  result.informed_by, result.run_id, result.activity)


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
    "empirical": OrgType(
        name="empirical",
        title="Empirical Lab",
        description="Turns a research question into a hypothesis tested by a reproducible "
        "experiment. A claim ships only if running the experiment supports it — twice.",
        input_noun="a research question",
        produces="a hypothesis backed by a reproducible experiment (or an honest refutation)",
        verified_by="the experiment is security-scanned, then run repeatedly; it must reproduce "
        "and the measured data — not the model's claim — must satisfy the prediction",
        goal_hint="do small-model ensembles beat a single larger model on accuracy?",
        build=_run_empirical,
        roster=empirical_roster,
    ),
    # --- Presets: products on the existing verification models, not new orgs. ---
    "newsroom": OrgType(
        name="newsroom",
        title="Newsroom (preset)",
        description="A grounded news article — a preset of the Research org. Same verification "
        "(every claim cited, resolves, quoted verbatim); journalism is the framing, not a new model.",
        input_noun="a story topic and its sources",
        produces="a grounded article (every claim traceable to a source)",
        verified_by="grounding — the Research org's gates, unchanged",
        goal_hint="what the new city budget changes for local schools",
        build=lambda g, p, m, sources=None: _run_grounded_preset(build_article, "newsroom", g, p, m, sources),
        roster=research_roster,
        needs_sources=True,
    ),
    "education": OrgType(
        name="education",
        title="Education (preset)",
        description="A grounded teaching lesson — a preset of the Research org. The lesson stays "
        "anchored to its sources; same grounding gates, framed for learners.",
        input_noun="a lesson topic and its sources",
        produces="a grounded lesson (every claim traceable to a source)",
        verified_by="grounding — the Research org's gates, unchanged",
        goal_hint="how a bill becomes a law",
        build=lambda g, p, m, sources=None: _run_grounded_preset(build_lesson, "education", g, p, m, sources),
        roster=research_roster,
        needs_sources=True,
    ),
    "startup": OrgType(
        name="startup",
        title="Startup Factory (preset)",
        description="Composes the Web org (a landing page) and the Software org (an MVP function). "
        "Each part keeps its own gates; 'is it profitable?' is the market's verdict, not verified here.",
        input_noun="a startup idea",
        produces="a verified landing page + a verified MVP function",
        verified_by="the Web org's render gates AND the Software org's execution gates — composed",
        goal_hint="a tool that finds profitable opportunities in poker",
        build=lambda g, p, m, sources=None: _run_composition(build_startup, "startup", g, p, m),
        roster=None,
    ),
    "game": OrgType(
        name="game",
        title="Game Studio (preset)",
        description="Composes the Production org (a concept trailer — consistency) and the Software "
        "org (a gameplay function — execution). 'Is it fun?' stays the human tier.",
        input_noun="a game idea",
        produces="a verified production chain + a verified gameplay function",
        verified_by="the Production org's consistency gates AND the Software org's execution gates",
        goal_hint="a roguelike about pirates",
        build=lambda g, p, m, sources=None: _run_composition(build_game, "game", g, p, m),
        roster=None,
    ),
}


def get_org(name: str) -> OrgType:
    if name not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown org type {name!r} (registered: {known})")
    return REGISTRY[name]
