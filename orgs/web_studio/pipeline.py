"""P14b — the Web Studio run: goal -> page-spec -> page, gated by a real browser.

The spec must name what the page must contain before anyone writes HTML (no synthesis before
the constraints are real — the doctrine). Then the developer writes a page; it is rendered
ONCE per attempt and the whole gate chain decides on that single render; on rejection the
developer re-writes with the failing gates' evidence. Same spine as the software org — only
the substrate (a browser) and the cast changed. That is the reusability claim, demonstrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.artifact import Artifact, Determinism
from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.web_studio.agents import DesignerAgent, WebDeveloperAgent
from orgs.web_studio.browser import BrowserExecutor
from orgs.web_studio.gates import A11yGate, LayoutGate, RenderGate, StructureGate
from orgs.web_studio.spec import PageSpecGate, parse_page_spec


@dataclass
class PageResult:
    spec_outcome: Outcome
    page_outcome: Outcome | None  # None if the spec was rejected first
    accepted: bool
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def _feedback(outcome: Outcome) -> str:
    failed = [
        r
        for r in outcome.gate_results
        if r.determinism is Determinism.HARD and not r.passed and r.gate_name != "validation"
    ]
    return "; ".join(f"{r.gate_name}: {r.evidence}" for r in failed)


def build_page(
    goal: str, provider: ModelProvider, memory: MemoryStore, *, max_attempts: int = 3
) -> PageResult:
    run = Run(goal=goal, memory=memory)
    recalled = memory.recall(goal, categories=["failure", "lesson", "decision"], limit=3)
    lessons = format_lessons(recalled)
    informed_by = [record.id for record in recalled]

    def result(spec_o: Outcome, page_o: Outcome | None, accepted: bool) -> PageResult:
        return PageResult(spec_o, page_o, accepted, informed_by, run.id, list(run.log))

    # EXPLAIN — the spec names the page's contract before any HTML exists. Retry on rejection
    # with the gate's feedback, so a malformed spec self-corrects instead of killing the build.
    def propose_spec(feedback: str | None) -> Artifact:
        art = DesignerAgent(provider).propose(goal, lessons=lessons, feedback=feedback)
        art.provenance.informed_by.extend(informed_by)
        return art

    spec_outcome = run.attempt(propose_spec, [PageSpecGate()])
    if not spec_outcome.accepted:
        return result(spec_outcome, None, False)
    spec = parse_page_spec(spec_outcome.artifact.payload)
    required = spec.required_elements

    # SYNTHESIZE + VERIFY — render once per attempt; the whole chain rules on that render;
    # on rejection the developer fixes itself with the failing gates' evidence.
    executor = BrowserExecutor()
    feedback: str | None = None
    best: Outcome | None = None
    best_score = -1
    for attempt in range(1, max_attempts + 1):
        page_artifact = WebDeveloperAgent(provider).propose(
            spec, parent_id=spec_outcome.artifact.id, lessons=lessons, feedback=feedback
        )
        page_artifact.provenance.informed_by.extend(informed_by)
        rendered = executor.render(page_artifact.payload, required)
        gates = [
            RenderGate(rendered),
            LayoutGate(rendered),
            StructureGate(rendered, required),
            A11yGate(rendered),
            ValidationGate(),  # final authority — must run last
        ]
        outcome = run.submit(page_artifact, gates)
        if outcome.accepted:
            return result(spec_outcome, outcome, True)
        score = sum(
            1 for r in outcome.gate_results if r.determinism is Determinism.HARD and r.passed
        )
        if score > best_score:
            best_score, best = score, outcome
        feedback = _feedback(outcome)

    assert best is not None
    return result(spec_outcome, best, False)
