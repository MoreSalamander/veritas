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
    preamble: str | None = None,
) -> ReportResult:
    """`vouched` maps any corpus source id drawn from the Knowledge Graph (commons) -> its attribution
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
        context = f"{preamble}\n\n{lessons}" if preamble and lessons else (preamble or lessons)
        art = ResearcherAgent(provider).propose(topic, corpus, lessons=context, feedback=feedback)
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


class AcquisitionEmpty(LookupError):
    """Every planned angle came back empty — there is nothing to ground."""


@dataclass
class IntelligenceResult:
    """A ReportResult plus the intelligence around it: the plan that drove
    acquisition, the sources each angle brought back, and the context graph
    extracted from the verified report."""

    report: ReportResult
    plan: "ResearchPlan"
    sources: list["AcquiredSource"]
    context_graph: dict

    @property
    def accepted(self) -> bool:
        return self.report.accepted


def build_intelligence(
    topic: str,
    provider: ModelProvider,
    memory: MemoryStore,
    search_client,
    *,
    judge: ModelProvider | None = None,
    per_angle: int = 3,
) -> IntelligenceResult:
    """The full research intelligence flow.

    1. Recall what the org already knows (entities from prior runs) — the
       avoid-relearning briefing.
    2. The planner proposes; parse_plan decides (one feedback retry, then
       the parse error is the honest answer).
    3. The plan's angles fan out in parallel over the live search seam.
    4. The researcher extracts claims + the graph from the pinned corpus;
       the SAME six grounding gates rule. Nothing about verification
       changed by getting wider.
    5. Verified entities and relationships persist to org memory, so the
       next run on nearby ground starts briefed.
    """
    from engine.artifact import _new_id
    from engine.memory import MemoryRecord
    from orgs.research_studio.agents import PlannerAgent
    from orgs.research_studio.intelligence import (
        AcquiredSource, ResearchPlan, acquire_parallel, parse_plan, PlanParseError,
    )
    from orgs.research_studio.report import parse_report, ReportParseError

    # 1 — the avoid-relearning briefing, from this org's own memory.
    known = memory.recall(topic, categories=["entity"], limit=8)
    kg_brief = None
    if known:
        names = "; ".join(r.title for r in known)
        kg_brief = (
            "KNOWN ENTITIES from prior research on nearby topics (context, "
            f"not law — re-verify anything you reuse): {names}"
        )

    # 2 — plan: propose -> parse, one honest retry.
    planner = PlannerAgent(provider)
    raw = planner.propose(topic, briefing=kg_brief)
    try:
        plan = parse_plan(raw, topic)
    except PlanParseError as exc:
        raw = planner.propose(topic, briefing=kg_brief, feedback=str(exc))
        plan = parse_plan(raw, topic)  # a second failure raises — the honest answer

    # 3 — parallel acquisition across the plan's angles.
    sources = acquire_parallel(plan, search_client, per_angle=per_angle)
    if not sources:
        raise AcquisitionEmpty(
            f"every angle ({', '.join(plan.angles)}) came back empty for: {topic}"
        )
    corpus: Corpus = {f"src{i + 1}": s.corpus_entry() for i, s in enumerate(sources)}

    # 4 — grounded extraction under the unchanged gates.
    result = build_report(
        topic, corpus, provider, memory, judge=judge,
        preamble=plan.brief() + (f"\n\n{kg_brief}" if kg_brief else ""),
    )

    # 5 — knowledge persistence + the context graph, from the VERIFIED report
    # only. A refused draft teaches lessons (build_report already handles
    # that); it never populates the knowledge layer.
    context_graph: dict = {"topic": topic, "entities": [], "relationships": [], "open_questions": []}
    art = getattr(result.report_outcome, "artifact", None)
    if art is not None:
        try:
            report = parse_report(art.payload)
            context_graph = {
                "topic": topic,
                "entities": [
                    {"name": e.name, "type": e.type, "description": e.description}
                    for e in report.entities
                ],
                "relationships": [
                    {"source": r.source, "relation": r.relation, "target": r.target,
                     "claim_index": r.claim_index}
                    for r in report.relationships
                ],
                "open_questions": list(report.open_questions),
            }
        except ReportParseError:
            pass  # a garbled draft has no graph; the verdict already says so
    if result.accepted and context_graph["entities"]:
        existing_titles = {
            r.title for r in memory.load_all() if r.category == "entity"
        }
        import json as _json
        for ent in context_graph["entities"]:
            if ent["name"] in existing_titles:
                continue
            memory.persist(MemoryRecord(
                category="entity",
                title=ent["name"],
                body=_json.dumps(ent),
                tags=["research-kg", ent["type"]],
                provenance={"topic": topic, "run_id": result.run_id},
            ))
        for rel in context_graph["relationships"]:
            memory.persist(MemoryRecord(
                category="relationship",
                title=f"{rel['source']} {rel['relation']} {rel['target']}",
                body=_json.dumps(rel),
                tags=["research-kg", rel["relation"]],
                provenance={"topic": topic, "run_id": result.run_id},
            ))

    return IntelligenceResult(
        report=result, plan=plan, sources=list(sources), context_graph=context_graph,
    )
