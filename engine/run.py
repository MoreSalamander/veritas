"""The Run — the deterministic state machine the organization is.

An organization is not a chatroom of agents. It is a state machine that walks
artifacts through Explain -> Synthesize -> Verify -> Persist, where agents only
fill the proposal slots and gates make every decision.

Phase 0 implements the spine: VERIFY (run the gates) and PERSIST (accept to
memory, or reject to failure memory). EXPLAIN and SYNTHESIZE are where real
proposers (LLMs) plug in at Phase 1 — for now an artifact arrives already
PROPOSED and the engine decides its fate honestly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from engine.artifact import Artifact, Determinism, GateResult, _new_id, _now
from engine.gate import Gate
from engine.memory import MemoryRecord, MemoryStore


class Phase(str, Enum):
    EXPLAIN = "explain"
    SYNTHESIZE = "synthesize"
    VERIFY = "verify"
    PERSIST = "persist"
    COMPLETE = "complete"


@dataclass
class ActivityEntry:
    phase: Phase
    actor: str
    message: str
    at: str = field(default_factory=_now)


@dataclass
class Outcome:
    artifact: Artifact
    accepted: bool
    gate_results: list[GateResult]
    memory_path: Path


class Run:
    def __init__(self, goal: str, memory: MemoryStore, run_id: str | None = None) -> None:
        self.goal = goal
        self.memory = memory
        self.id = run_id or _new_id("run")
        self.log: list[ActivityEntry] = []
        self.phase: Phase = Phase.EXPLAIN

    def _activity(self, phase: Phase, actor: str, message: str) -> None:
        self.phase = phase
        self.log.append(ActivityEntry(phase=phase, actor=actor, message=message))

    def verify(self, artifact: Artifact, gates: Sequence[Gate]) -> list[GateResult]:
        """Run every gate, recording each verdict onto the artifact's provenance."""
        results: list[GateResult] = []
        for gate in gates:
            result = gate.check(artifact)
            artifact.record_gate(result)
            results.append(result)
            verdict = "PASS" if result.passed else "FAIL"
            self._activity(Phase.VERIFY, gate.name, f"{verdict}: {result.evidence}")
        return results

    def persist(self, artifact: Artifact, gate_results: list[GateResult]) -> Outcome:
        """Accept only if the HARD gates earned it. Soft gates are advisory.

        Invariant: zero HARD gates can never accept — you cannot be accepted on
        judgment alone. A soft-gate failure is recorded as a finding, not a block.
        """
        hard = [r for r in gate_results if r.determinism is Determinism.HARD]
        soft_failures = [
            r for r in gate_results if r.determinism is Determinism.SOFT and not r.passed
        ]
        accepted = len(hard) > 0 and all(r.passed for r in hard)
        if accepted:
            because = "all hard gates passed: " + ", ".join(r.gate_name for r in hard)
            if soft_failures:
                because += " | soft findings noted: " + ", ".join(
                    r.gate_name for r in soft_failures
                )
            artifact.accept(because)
            record = MemoryRecord.from_accepted_artifact(artifact)
        else:
            artifact.reject()
            if not hard:
                reason = "no hard verification ran — cannot accept on judgment alone"
            else:
                failed = [r for r in hard if not r.passed]
                reason = "; ".join(f"{r.gate_name}: {r.evidence}" for r in failed)
            record = MemoryRecord.from_rejected_artifact(artifact, reason)

        path = self.memory.persist(record)
        destination = "accepted -> institutional" if accepted else "rejected -> failures"
        self._activity(Phase.PERSIST, "memory", f"{destination}: {path.name}")
        self.phase = Phase.COMPLETE
        return Outcome(artifact=artifact, accepted=accepted, gate_results=gate_results, memory_path=path)

    def submit(self, artifact: Artifact, gates: Sequence[Gate]) -> Outcome:
        """Walk a proposed artifact through Verify -> Persist. The whole spine."""
        results = self.verify(artifact, gates)
        return self.persist(artifact, results)
