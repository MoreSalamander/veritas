"""The Gate — the decision engine.

A gate is a function `Artifact -> GateResult`. It is the only thing in Veritas
allowed to say yes or no. Deterministic wherever a real check exists; explicitly
SOFT where it doesn't. The LLM proposes; the gate decides.

This is the behavior side of the two primitives. The data side (GateResult,
Determinism) lives in artifact.py to keep that module a dependency-free leaf.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from engine.artifact import Artifact, Determinism, GateResult


class Gate(ABC):
    """A deterministic-preferred check. Subclasses MUST declare their determinism
    level honestly via the class attributes below."""

    name: str
    determinism: Determinism

    @abstractmethod
    def check(self, artifact: Artifact) -> GateResult:
        """Evaluate the artifact. Return a pass/fail verdict plus the evidence
        for it — never a bare boolean. The evidence is what makes the decision
        explainable (Rule 4)."""
        raise NotImplementedError

    def _result(self, passed: bool, evidence: str) -> GateResult:
        return GateResult(
            gate_name=self.name,
            determinism=self.determinism,
            passed=passed,
            evidence=evidence,
        )
