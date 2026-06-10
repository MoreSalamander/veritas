"""Watch the organization read its own memory before it acts.

    python scripts/demo_learning.py

We seed a realistic prior failure (an earlier vague spec for the same kind of goal),
then run a real build. Before proposing anything, the org recalls that failure, feeds
it to the proposers, and stamps what it recalled into the new artifacts' provenance.

The *behavioral* avoidance (failing once, then succeeding) is proven deterministically
in tests/test_learning.py; here we show the machinery running against a live model.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from engine.artifact import Artifact, Provenance
from engine.memory import MemoryRecord, MemoryStore
from engine.model import OllamaProvider
from orgs.software_studio.pipeline import build_software


def seed_prior_failure(memory: MemoryStore) -> Path:
    art = Artifact(
        type="spec",
        owner="spec-agent",
        payload="(an earlier, vaguer attempt)",
        provenance=Provenance(
            created_by="spec-agent",
            rationale="specification for goal: reverse a string",
        ),
    )
    record = MemoryRecord.from_rejected_artifact(
        art, reason="spec not executable: no concrete input/output cases"
    )
    return memory.persist(record)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("VERITAS_MODEL", "llama3.1:8b"))
    args = parser.parse_args()

    memory = MemoryStore(Path("./.demo_memory"))
    seeded = seed_prior_failure(memory)
    print(f"seeded a prior failure: {seeded.parent.name}/{seeded.name}\n")

    goal = "a function that reverses a string"
    recalled = memory.recall(goal, categories=["failure", "lesson"])
    print(f"goal : {goal}")
    print(f"model: {args.model}\n")
    print(f"the org recalled {len(recalled)} prior memory(ies) before acting:")
    for record in recalled:
        reason = record.provenance.get("rejected_because", "")
        print(f"  - [{record.category}] {record.title}  ({reason})")
    print()

    result = build_software(goal, OllamaProvider(model=args.model), memory)
    print(f"informed_by stamped into this build: {result.informed_by}")
    if result.code_outcome is not None:
        code = result.code_outcome
        print(f"CODE -> {'ACCEPTED' if code.accepted else 'REJECTED'}")
        print(f"  code provenance.informed_by = {code.artifact.provenance.informed_by}")


if __name__ == "__main__":
    main()
