"""The Artifact — the load-bearing object of the whole organization.

Nothing in Veritas is "just a file." Every artifact carries who made it, why it
exists, what validated it, and why it was accepted. The struct *is* the trust
system. (See README.md §4 — The Validation Doctrine.)

This module is the data side of the two primitives (Artifact + Gate) and imports
nothing else from the engine, so it stays a leaf that everything else can build on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "art") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ArtifactStatus(str, Enum):
    PROPOSED = "proposed"  # an agent's output — a candidate, never a fact
    ACCEPTED = "accepted"  # a gate said yes; it may enter organizational memory
    REJECTED = "rejected"  # a gate said no; it becomes a failure record


class Determinism(str, Enum):
    """Whether a gate's verdict is machine-checkable (HARD) or a judgment (SOFT).

    A SOFT gate must never be presented as a HARD one. That honesty is the
    difference between a trust system and a polite committee of LLMs.
    """

    HARD = "hard"  # tests, types, schema, scans — no opinion involved
    SOFT = "soft"  # a judge-LLM's opinion — recorded, but never disguised as proof
    HUMAN = "human"  # a person signed off — the proper verifier for feel/taste (create mode)


@dataclass(frozen=True)
class GateResult:
    """The verdict of one gate against one artifact. The data side of a Gate."""

    gate_name: str
    determinism: Determinism
    passed: bool
    evidence: str
    checked_at: str = field(default_factory=_now)


@dataclass
class Provenance:
    """The trust trail. Every accepted artifact must answer: who made it, why it
    exists, what validated it, and why it was accepted (Rules 2-5)."""

    created_by: str
    rationale: str
    gate_results: list[GateResult] = field(default_factory=list)
    accepted_because: str | None = None
    informed_by: list[str] = field(default_factory=list)  # memory ids that shaped this
    created_at: str = field(default_factory=_now)


@dataclass
class Artifact:
    type: str
    owner: str
    payload: str
    provenance: Provenance
    parent_id: str | None = None
    status: ArtifactStatus = ArtifactStatus.PROPOSED
    confidence: float | None = None
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=_now)

    @classmethod
    def propose(
        cls,
        *,
        type: str,
        owner: str,
        payload: str,
        rationale: str,
        parent_id: str | None = None,
        confidence: float | None = None,
    ) -> "Artifact":
        """An agent proposes an artifact. It enters the world as PROPOSED — a
        candidate that has earned nothing yet."""
        return cls(
            type=type,
            owner=owner,
            payload=payload,
            parent_id=parent_id,
            confidence=confidence,
            provenance=Provenance(created_by=owner, rationale=rationale),
        )

    def record_gate(self, result: GateResult) -> None:
        self.provenance.gate_results.append(result)

    def accept(self, because: str) -> None:
        self.status = ArtifactStatus.ACCEPTED
        self.provenance.accepted_because = because

    def reject(self) -> None:
        self.status = ArtifactStatus.REJECTED
