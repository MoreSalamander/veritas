"""The Docs Studio run: topic -> outline -> document, gated on the same engine.

Structurally identical to the software studio's pipeline — recall lessons, propose an
outline, gate it, then write the document and let the cast review it — but with a
different cast and different domain gates. The final authority (ValidationGate) and the
learning machinery (recall + format_lessons) are the shared engine, untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.docs_studio.agents import OutlineAgent, WriterAgent
from orgs.docs_studio.gates import ExamplesRunGate, ReadabilityGate, StructureGate
from orgs.docs_studio.gates import OutlineScorerGate
from orgs.docs_studio.spec import parse_docs_spec


@dataclass
class DocsResult:
    outline_outcome: Outcome
    doc_outcome: Outcome | None  # None when the outline was rejected first
    accepted: bool
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build_doc(topic: str, provider: ModelProvider, memory: MemoryStore) -> DocsResult:
    run = Run(goal=topic, memory=memory)

    recalled = memory.recall(topic, categories=["failure", "lesson"], limit=3)
    lessons = format_lessons(recalled)
    informed_by = [record.id for record in recalled]

    # EXPLAIN — the outline must be usable before anyone writes.
    outline_artifact = OutlineAgent(provider).propose(topic, lessons=lessons)
    outline_artifact.provenance.informed_by.extend(informed_by)
    outline_outcome = run.submit(outline_artifact, [OutlineScorerGate()])
    if not outline_outcome.accepted:
        return DocsResult(outline_outcome, None, False, informed_by, run.id, list(run.log))
    spec = parse_docs_spec(outline_artifact.payload)

    # SYNTHESIZE + VERIFY — write the doc; the cast reviews it; Validation has final say.
    doc_artifact = WriterAgent(provider).propose(spec, parent_id=outline_artifact.id, lessons=lessons)
    doc_artifact.provenance.informed_by.extend(informed_by)
    doc_outcome = run.submit(
        doc_artifact,
        [
            StructureGate(spec),
            ExamplesRunGate(),
            ReadabilityGate(),
            ValidationGate(),  # the shared final authority — must run last
        ],
    )
    return DocsResult(
        outline_outcome, doc_outcome, doc_outcome.accepted, informed_by, run.id, list(run.log)
    )
