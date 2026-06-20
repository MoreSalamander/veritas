"""Presets — products built on the EXISTING verification models, no new engine.

Two ways the substrate generalizes, both proven here:

1. REUSE a verification model. A newsroom article and a teaching lesson are both verified by
   GROUNDING — exactly the Research org's model (every claim cited, resolves, quoted verbatim). So
   they are the research pipeline with a different product framing, not new orgs. The "fact-checker"
   is the grounding gate layer; nothing new is verified.

2. COMPOSE verification models. A startup is a landing page (verified by the Web org) plus an MVP
   (verified by the Software org); a game is a production (consistency) plus gameplay code (execution).
   Each sub-artifact is judged by its own org's gates; the composition just chains them. What can't be
   verified — "is this profitable?", "is this fun?" — stays an honest human/market bet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from engine.memory import MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome
from orgs.production_studio.pipeline import build_production
from orgs.research_studio.pipeline import ReportResult, build_report
from orgs.research_studio.report import Corpus
from orgs.software_studio.builder import build
from orgs.web_studio.pipeline import build_page


# --- 1. Research-grounding presets (same model, different product) ------------------------

def build_article(topic: str, corpus: Corpus, provider: ModelProvider, memory: MemoryStore) -> ReportResult:
    """Newsroom: a grounded news article — the Research org's grounding, framed as journalism."""
    return build_report(f"a grounded news article about {topic}", corpus, provider, memory)


def build_lesson(topic: str, corpus: Corpus, provider: ModelProvider, memory: MemoryStore) -> ReportResult:
    """Education: a grounded teaching lesson — same grounding verification, framed for learners."""
    return build_report(f"a clear teaching lesson, grounded in the sources, about {topic}",
                        corpus, provider, memory)


# --- 2. Composition presets (orgs chained; each part keeps its own gates) ------------------

@dataclass
class CompositionResult:
    outcomes: list[Outcome]
    accepted: bool  # every composed org shipped
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


@dataclass
class _Part:
    outcomes: list[Outcome]
    accepted: bool
    informed_by: list[str]
    activity: list[ActivityEntry]


def _combine(parts: list[_Part]) -> CompositionResult:
    """Chain sub-builds: all their artifacts in order, accepted only if every part shipped."""
    outcomes: list[Outcome] = []
    informed: list[str] = []
    activity: list[ActivityEntry] = []
    for p in parts:
        outcomes.extend(p.outcomes)
        informed.extend(p.informed_by)
        activity.extend(p.activity)
    return CompositionResult(
        outcomes=outcomes, accepted=all(p.accepted for p in parts),
        informed_by=informed, run_id=f"compose_{uuid4().hex}", activity=activity,
    )


def build_startup(brief: str, provider: ModelProvider, memory: MemoryStore) -> CompositionResult:
    """Startup Factory: a landing page (Web org) + an MVP function (Software org). Profitability is
    not verifiable — that's the market's verdict, the honest human bet."""
    web = build_page(f"a landing page for {brief}", provider, memory)
    web_outcomes = [web.spec_outcome] + ([web.page_outcome] if web.page_outcome else [])
    sw = build(f"a core function that powers {brief}", provider, memory)
    return _combine([
        _Part(web_outcomes, web.accepted, web.informed_by, web.activity),
        _Part(sw.outcomes, sw.accepted, sw.informed_by, sw.activity),
    ])


def build_game(brief: str, provider: ModelProvider, memory: MemoryStore) -> CompositionResult:
    """Game Studio: a production (concept/script/storyboard — consistency) + a gameplay function
    (Software org — execution). Whether it's fun stays the human tier."""
    prod = build_production(f"a short narrated concept trailer for the game: {brief}", provider, memory)
    sw = build(f"a core gameplay function for {brief}", provider, memory)
    return _combine([
        _Part(prod.outcomes, prod.accepted, prod.informed_by, prod.activity),
        _Part(sw.outcomes, sw.accepted, sw.informed_by, sw.activity),
    ])
