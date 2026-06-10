"""Watch the spine breathe: one artifact earns acceptance, one gets rejected.

    python scripts/demo_spine.py

No LLM, no network — just the Artifact -> Gate -> Run -> Memory loop, proving
that acceptance and rejection are both real and both leave a provenance trail.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from engine.artifact import Artifact, Determinism
from engine.gate import Gate
from engine.memory import MemoryStore
from engine.run import Run


class NonEmptyPayloadGate(Gate):
    """A genuinely deterministic gate: the payload must not be blank."""

    name = "payload-nonempty"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact):
        ok = bool(artifact.payload.strip())
        return self._result(ok, "payload is non-empty" if ok else "payload is empty")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        memory = MemoryStore(Path(tmp))

        good = Artifact.propose(
            type="code", owner="developer",
            payload="def add(a, b):\n    return a + b\n",
            rationale="implements addition",
        )
        bad = Artifact.propose(
            type="code", owner="developer",
            payload="   ",
            rationale="forgot to write anything",
        )

        for label, artifact in (("GOOD", good), ("EMPTY", bad)):
            outcome = Run(goal="demo", memory=memory).submit(artifact, [NonEmptyPayloadGate()])
            verdict = "ACCEPTED" if outcome.accepted else "REJECTED"
            print(f"\n=== {label} artifact -> {verdict} ===")
            print(f"  status     : {outcome.artifact.status.value}")
            print(f"  memory     : {outcome.memory_path.parent.name}/{outcome.memory_path.name}")
            print("  record:")
            for line in outcome.memory_path.read_text().splitlines():
                print(f"    {line}")


if __name__ == "__main__":
    main()
