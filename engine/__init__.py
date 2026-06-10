"""Veritas engine — the reusable substrate every organization runs on.

The two primitives — Artifact (trust object) and Gate (decision) — plus the Run
state machine and institutional Memory. Only the specialized agents change per
organization type; this engine stays constant.
"""

from engine.artifact import (
    Artifact,
    ArtifactStatus,
    Determinism,
    GateResult,
    Provenance,
)
from engine.gate import Gate
from engine.memory import MemoryRecord, MemoryStore
from engine.run import ActivityEntry, Outcome, Phase, Run

__all__ = [
    "Artifact",
    "ArtifactStatus",
    "Determinism",
    "GateResult",
    "Provenance",
    "Gate",
    "MemoryRecord",
    "MemoryStore",
    "ActivityEntry",
    "Outcome",
    "Phase",
    "Run",
]
