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

import time
from collections.abc import Callable, Sequence
from contextvars import ContextVar
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
    duration_ms: float = 0.0
    at: str = field(default_factory=_now)


# A live tap on the activity stream, for the Hub's run timeline. It is purely
# observational — set per execution context (per worker thread), default off, and a
# misbehaving listener can never affect a verdict. The decision engine does not know or
# care that anyone is watching.
_activity_listener: ContextVar[Callable[[ActivityEntry], None] | None] = ContextVar(
    "veritas_activity_listener", default=None
)


def set_activity_listener(listener: Callable[[ActivityEntry], None] | None) -> None:
    _activity_listener.set(listener)


def emit_activity(phase: Phase, actor: str, message: str, duration_ms: float = 0.0) -> None:
    """Emit a one-off event to the live listener (if any), without a Run — lets a proposer announce
    it's working so the Hub can light that actor's box. Purely observational; a watcher error is
    swallowed and can never disturb the run."""
    listener = _activity_listener.get()
    if listener is not None:
        try:
            listener(ActivityEntry(phase=phase, actor=actor, message=message, duration_ms=duration_ms))
        except Exception:
            pass


@dataclass
class Outcome:
    artifact: Artifact
    accepted: bool
    gate_results: list[GateResult]
    memory_path: Path


class Run:
    def __init__(self, goal: str, memory: MemoryStore, run_id: str | None = None,
                 max_attempts: int = 3) -> None:
        self.goal = goal
        self.memory = memory
        self.id = run_id or _new_id("run")
        self.log: list[ActivityEntry] = []
        self.phase: Phase = Phase.EXPLAIN
        # The default retry budget for attempt() — set from the provider so a thinking model
        # caps lower (its retries are slow and rarely pay off). attempt() can still override.
        self.max_attempts = max_attempts

    def _activity(self, phase: Phase, actor: str, message: str, duration_ms: float = 0.0) -> None:
        self.phase = phase
        entry = ActivityEntry(phase=phase, actor=actor, message=message, duration_ms=duration_ms)
        self.log.append(entry)
        listener = _activity_listener.get()
        if listener is not None:
            try:
                listener(entry)
            except Exception:  # a watcher must never be able to disturb the run
                pass

    def verify(self, artifact: Artifact, gates: Sequence[Gate]) -> list[GateResult]:
        """Run every gate, recording each verdict onto the artifact's provenance."""
        results: list[GateResult] = []
        for gate in gates:
            started = time.perf_counter()
            result = gate.check(artifact)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            artifact.record_gate(result)
            results.append(result)
            verdict = "PASS" if result.passed else "FAIL"
            self._activity(Phase.VERIFY, gate.name, f"{verdict}: {result.evidence}", elapsed_ms)
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

    def _feedback(self, outcome: Outcome) -> str:
        failed = [r for r in outcome.gate_results if r.determinism is Determinism.HARD and not r.passed]
        return "; ".join(f"{r.gate_name}: {r.evidence}" for r in failed)

    def attempt(
        self,
        propose: Callable[[str | None], Artifact],
        gates: Sequence[Gate],
        max_attempts: int | None = None,
    ) -> Outcome:
        """The retry loop: propose, gate, and on rejection re-propose with the failing
        gates' evidence as feedback — up to max_attempts (defaults to the Run's budget, which
        a thinking model caps lower). Lets the org fix its own work instead of dying on the
        first miss. If no attempt fully passes, returns the best one (most hard gates passed).
        The feedback drives the *implementation* to fix itself; the verification criteria are
        never weakened to force a pass."""
        limit = max_attempts if max_attempts is not None else self.max_attempts
        feedback: str | None = None
        best: Outcome | None = None
        best_score = -1
        for n in range(1, limit + 1):
            outcome = self.submit(propose(feedback), gates)
            if outcome.accepted:
                if n > 1:
                    self._activity(Phase.SYNTHESIZE, "retry", f"accepted on attempt {n}")
                return outcome
            score = sum(
                1 for r in outcome.gate_results if r.determinism is Determinism.HARD and r.passed
            )
            if score > best_score:
                best_score, best = score, outcome
            feedback = self._feedback(outcome)
            if n < limit:
                self._activity(
                    Phase.SYNTHESIZE, "retry",
                    f"attempt {n} rejected ({score} hard gates passed) — re-proposing with feedback",
                )
        assert best is not None
        return best
