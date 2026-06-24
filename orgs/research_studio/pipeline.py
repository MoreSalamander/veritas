"""P16b — the Research Studio run: topic + pinned sources -> a grounded report.

Same spine as the other orgs — only the cast and the verification model changed. The
Researcher proposes a report; the grounding gates rule on it; on rejection it self-corrects
with the failing gate's evidence. The hard floor (cited / resolves / verbatim) guarantees
grounding; the soft support gate adds an advisory judgment on top, never a block.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.artifact import Artifact
from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.research_studio.agents import ResearcherAgent
from orgs.research_studio.gates import (
    CitationsResolveGate,
    ClaimsCitedGate,
    QuotesVerbatimGate,
    ReportScorerGate,
    SupportGate,
    VouchedAttributionGate,
)
from orgs.research_studio.report import Corpus


@dataclass
class ReportResult:
    report_outcome: Outcome
    accepted: bool
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build_report(
    topic: str, corpus: Corpus, provider: ModelProvider, memory: MemoryStore,
    *, judge: ModelProvider | None = None, vouched: dict[str, str] | None = None,
) -> ReportResult:
    """`vouched` maps any corpus source id drawn from the Second Brain (commons) -> its attribution
    label. Those sources are human-vouched but UNVERIFIED, so a claim leaning on one must attribute
    it, not state it as fact (VouchedAttributionGate). The commons source ids also flow into the
    report's `informed_by`, so the unverified provenance travels with whatever the run produces."""
    vouched = vouched or {}
    run = Run(goal=topic, memory=memory)
    recalled = memory.recall(topic, categories=["failure", "lesson", "decision"], limit=3)
    lessons = format_lessons(recalled)
    # The vouched commons sources are part of what informed the run — keep that in provenance so a
    # downstream reader can see the work leaned on unverified, human-vouched material.
    informed_by = [record.id for record in recalled] + sorted(vouched)

    def propose(feedback: str | None) -> Artifact:
        art = ResearcherAgent(provider).propose(topic, corpus, lessons=lessons, feedback=feedback)
        art.provenance.informed_by.extend(informed_by)
        return art

    outcome = run.attempt(
        propose,
        [
            ReportScorerGate(),
            ClaimsCitedGate(),
            CitationsResolveGate(corpus),
            QuotesVerbatimGate(corpus),
            VouchedAttributionGate(vouched),  # HARD — commons tier may ground only attributed claims
            SupportGate(judge or provider, corpus),  # SOFT — advisory judgment
            ValidationGate(),  # final authority — must run last
        ],
    )
    return ReportResult(outcome, outcome.accepted, informed_by, run.id, list(run.log))
