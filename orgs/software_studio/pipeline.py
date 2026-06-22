"""The Software Studio run: goal -> spec -> code, gated at every boundary.

One Run walks the whole job so the activity log and memory are unified. The spec
must be accepted (executable) before the developer is ever asked to write code —
if the spec is rejected, the run ends there and the developer never runs. That
ordering is the doctrine: no synthesis before the constraints are real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.artifact import Artifact
from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.software_studio.agents import DeveloperAgent, DocAgent, QAAgent, SpecAgent
from orgs.software_studio.gates import (
    AcceptanceGate,
    ConsensusGate,
    ExamplesRunGate,
    PropertyGate,
    QAGate,
    SecurityScanGate,
    SpecScorerGate,
    SyntaxGate,
)
from orgs.software_studio.languages import (
    Language,
    LangAcceptanceGate,
    LangPropertyGate,
    LangSyntaxGate,
)
from orgs.software_studio.oracle import VotingOracle
from orgs.software_studio.spec import parse_spec


@dataclass
class StudioResult:
    spec_outcome: Outcome
    code_outcome: Outcome | None  # None when the spec was rejected first
    accepted: bool
    informed_by: list[str] = field(default_factory=list)  # memory ids recalled for this build
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)
    doc_outcome: Outcome | None = None  # set only when document=True and code shipped


def build_function(goal: str, provider: ModelProvider, memory: MemoryStore) -> StudioResult:
    """Phase 1 pipeline: goal -> spec -> code, with the core hard gates only."""
    run = Run(goal=goal, memory=memory, max_attempts=provider.retry_budget())

    spec_outcome = run.attempt(
        lambda fb: SpecAgent(provider).propose(goal, feedback=fb), [SpecScorerGate()]
    )
    if not spec_outcome.accepted:
        return StudioResult(spec_outcome, None, False, [], run.id, list(run.log))

    spec = parse_spec(spec_outcome.artifact.payload)
    code_artifact = DeveloperAgent(provider).propose(spec, parent_id=spec_outcome.artifact.id)
    code_outcome = run.submit(
        code_artifact,
        [
            SyntaxGate(spec.function_name),
            PropertyGate(spec.function_name, spec.properties),  # HARD: oracle-free
            AcceptanceGate(spec),  # SOFT: model-authored cases, advisory
        ],
    )
    return StudioResult(
        spec_outcome, code_outcome, code_outcome.accepted, [], run.id, list(run.log)
    )


def build_function_in(
    language: Language, goal: str, provider: ModelProvider, memory: MemoryStore
) -> StudioResult:
    """P15 — build a function in any language. The spec is language-agnostic (name, cases,
    oracle-free properties); only the developer's prompt and the gate harnesses change with
    the Language. Same spine as build_function — proof the org's verification model is one
    model, many languages."""
    run = Run(goal=goal, memory=memory, max_attempts=provider.retry_budget())

    spec_outcome = run.attempt(
        lambda fb: SpecAgent(provider).propose(goal, feedback=fb), [SpecScorerGate()]
    )
    if not spec_outcome.accepted:
        return StudioResult(spec_outcome, None, False, [], run.id, list(run.log))
    spec = parse_spec(spec_outcome.artifact.payload)
    cases = [{"args": c.args, "expected": c.expected} for c in spec.cases]

    def propose_code(feedback: str | None) -> Artifact:
        return DeveloperAgent(provider).propose(
            spec, parent_id=spec_outcome.artifact.id, feedback=feedback, language=language
        )

    code_outcome = run.attempt(
        propose_code,
        [
            LangSyntaxGate(language, spec.function_name),
            LangPropertyGate(language, spec.function_name, spec.properties),  # HARD authority
            LangAcceptanceGate(language, spec.function_name, cases),  # SOFT — model oracle
            ValidationGate(),
        ],
    )
    return StudioResult(
        spec_outcome, code_outcome, code_outcome.accepted, [], run.id, list(run.log)
    )


def build_software(
    goal: str,
    provider: ModelProvider,
    memory: MemoryStore,
    *,
    document: bool = False,
    oracle: VotingOracle | None = None,
) -> StudioResult:
    """The full cast reviews the code; Validation is the final authority. With
    document=True, the Doc agent (a role in THIS org, not a separate org) then
    documents the accepted function — and its examples are verified to run against
    the real implementation by the same examples-run gate. Docs are checked by
    executing code, the same verification model as the code, which is exactly why
    they belong here and not in an org of their own.

    Before proposing anything, the org recalls its own relevant failures and lessons
    and feeds them to the proposers — so it stops repeating its own mistakes. What
    was recalled is stamped into each artifact's provenance (informed_by)."""
    run = Run(goal=goal, memory=memory, max_attempts=provider.retry_budget())

    # The org reads its own memory first.
    recalled = memory.recall(goal, categories=["failure", "lesson", "decision"], limit=3)
    lessons = format_lessons(recalled)
    informed_by = [record.id for record in recalled]

    # EXPLAIN — the spec must be executable before anyone writes code. Retry on rejection with
    # the gate's feedback, so a local model's occasional non-executable spec self-corrects.
    def propose_spec(feedback: str | None) -> Artifact:
        art = SpecAgent(provider).propose(goal, lessons=lessons, feedback=feedback)
        art.provenance.informed_by.extend(informed_by)
        return art

    spec_outcome = run.attempt(propose_spec, [SpecScorerGate()])
    if not spec_outcome.accepted:
        return StudioResult(spec_outcome, None, False, informed_by, run.id, list(run.log))
    spec = parse_spec(spec_outcome.artifact.payload)

    # QA writes independent tests from the spec — never seeing the implementation.
    qa_cases = QAAgent(provider).propose_cases(spec)

    # SYNTHESIZE + VERIFY — the developer writes code; the cast reviews it; on rejection
    # the developer re-writes with the failing gates' evidence, up to a few attempts.
    def propose_code(feedback: str | None) -> Artifact:
        art = DeveloperAgent(provider).propose(
            spec, parent_id=spec_outcome.artifact.id, lessons=lessons, feedback=feedback
        )
        art.provenance.informed_by.extend(informed_by)
        return art

    gates = [
        SyntaxGate(spec.function_name),
        PropertyGate(spec.function_name, spec.properties),  # HARD behavioral authority
        AcceptanceGate(spec),  # SOFT — exact cases are a model-authored oracle
        SecurityScanGate(),
        QAGate(spec.function_name, qa_cases),
    ]
    if oracle is not None:  # SOFT graded-confidence vote, for the value gap properties can't reach
        gates.append(ConsensusGate(spec, oracle))
    gates.append(ValidationGate())  # final authority — must run last

    code_outcome = run.attempt(propose_code, gates)
    code_artifact = code_outcome.artifact

    # DOCUMENT — an optional role: document the accepted function, examples verified
    # against the real code. A failed doc does NOT un-ship a verified function.
    doc_outcome: Outcome | None = None
    if document and code_outcome.accepted:
        code_src = code_artifact.payload
        doc_artifact = DocAgent(provider).propose(
            spec, code_src, parent_id=code_artifact.id, lessons=lessons
        )
        doc_artifact.provenance.informed_by.extend(informed_by)
        doc_outcome = run.submit(
            doc_artifact,
            [
                ExamplesRunGate(preamble=code_src, must_reference=spec.function_name),
                ValidationGate(),
            ],
        )

    return StudioResult(
        spec_outcome, code_outcome, code_outcome.accepted, informed_by, run.id, list(run.log),
        doc_outcome=doc_outcome,
    )
