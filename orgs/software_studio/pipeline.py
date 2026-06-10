"""The Software Studio run: goal -> spec -> code, gated at every boundary.

One Run walks the whole job so the activity log and memory are unified. The spec
must be accepted (executable) before the developer is ever asked to write code —
if the spec is rejected, the run ends there and the developer never runs. That
ordering is the doctrine: no synthesis before the constraints are real.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.memory import MemoryRecord, MemoryStore
from engine.model import ModelProvider
from engine.run import Outcome, Run
from orgs.software_studio.agents import DeveloperAgent, QAAgent, SpecAgent
from orgs.software_studio.gates import (
    AcceptanceGate,
    QAGate,
    SecurityScanGate,
    SpecScorerGate,
    SyntaxGate,
    ValidationGate,
)
from orgs.software_studio.spec import parse_spec


@dataclass
class StudioResult:
    spec_outcome: Outcome
    code_outcome: Outcome | None  # None when the spec was rejected first
    accepted: bool
    informed_by: list[str] = field(default_factory=list)  # memory ids recalled for this build


def _format_lessons(recalled: list[MemoryRecord]) -> str | None:
    if not recalled:
        return None
    lines = ["Lessons from past attempts at similar goals (avoid repeating these):"]
    for record in recalled:
        reason = record.provenance.get("rejected_because")
        if not reason:
            reason = record.body.splitlines()[0] if record.body else record.title
        lines.append(f"- {record.title}: {reason}")
    return "\n".join(lines)


def build_function(goal: str, provider: ModelProvider, memory: MemoryStore) -> StudioResult:
    """Phase 1 pipeline: goal -> spec -> code, with the core hard gates only."""
    run = Run(goal=goal, memory=memory)

    spec_artifact = SpecAgent(provider).propose(goal)
    spec_outcome = run.submit(spec_artifact, [SpecScorerGate()])
    if not spec_outcome.accepted:
        return StudioResult(spec_outcome=spec_outcome, code_outcome=None, accepted=False)

    spec = parse_spec(spec_artifact.payload)
    code_artifact = DeveloperAgent(provider).propose(spec, parent_id=spec_artifact.id)
    code_outcome = run.submit(
        code_artifact,
        [SyntaxGate(spec.function_name), AcceptanceGate(spec)],
    )
    return StudioResult(
        spec_outcome=spec_outcome,
        code_outcome=code_outcome,
        accepted=code_outcome.accepted,
    )


def build_software(goal: str, provider: ModelProvider, memory: MemoryStore) -> StudioResult:
    """Phase 2 pipeline: the full cast reviews the code. The code artifact carries
    every reviewer's verdict in one provenance trail (the README's Validation
    Doctrine example): syntax + acceptance + security (hard), QA (soft, advisory),
    and Validation as the final authority before anything persists.

    Before proposing anything, the org recalls its own relevant failures and lessons
    and feeds them to the proposers — so it stops repeating its own mistakes. What
    was recalled is stamped into each artifact's provenance (informed_by)."""
    run = Run(goal=goal, memory=memory)

    # The org reads its own memory first.
    recalled = memory.recall(goal, categories=["failure", "lesson"], limit=3)
    lessons = _format_lessons(recalled)
    informed_by = [record.id for record in recalled]

    # EXPLAIN — the spec must be executable before anyone writes code.
    spec_artifact = SpecAgent(provider).propose(goal, lessons=lessons)
    spec_artifact.provenance.informed_by.extend(informed_by)
    spec_outcome = run.submit(spec_artifact, [SpecScorerGate()])
    if not spec_outcome.accepted:
        return StudioResult(spec_outcome, None, False, informed_by)
    spec = parse_spec(spec_artifact.payload)

    # QA writes independent tests from the spec — never seeing the implementation.
    qa_cases = QAAgent(provider).propose_cases(spec)

    # SYNTHESIZE + VERIFY — the developer writes code; the whole cast reviews it.
    code_artifact = DeveloperAgent(provider).propose(
        spec, parent_id=spec_artifact.id, lessons=lessons
    )
    code_artifact.provenance.informed_by.extend(informed_by)
    code_outcome = run.submit(
        code_artifact,
        [
            SyntaxGate(spec.function_name),
            AcceptanceGate(spec),
            SecurityScanGate(),
            QAGate(spec.function_name, qa_cases),
            ValidationGate(),  # final authority — must run last
        ],
    )
    return StudioResult(spec_outcome, code_outcome, code_outcome.accepted, informed_by)
