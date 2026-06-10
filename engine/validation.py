"""The Validation gate — the org-agnostic final authority.

It decides nothing about a domain; it only reads an artifact's accumulated provenance
and confirms every HARD gate passed and provenance is complete. That makes it shared
substrate: the software studio and the docs studio both end their runs here. Nothing
enters memory without Validation's approval (Rule: Validation has the final say).
"""

from __future__ import annotations

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate


class ValidationGate(Gate):
    name = "validation"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        prior = artifact.provenance.gate_results  # all gates recorded before this one
        if not artifact.provenance.created_by or not artifact.provenance.rationale:
            return self._result(False, "withheld — incomplete provenance (owner/rationale)")
        hard = [r for r in prior if r.determinism is Determinism.HARD]
        if not hard:
            return self._result(False, "withheld — no hard verification to validate")
        failed = [r for r in hard if not r.passed]
        if failed:
            return self._result(
                False, "withheld — hard gate(s) failed: " + ", ".join(r.gate_name for r in failed)
            )
        soft_findings = [r for r in prior if r.determinism is Determinism.SOFT and not r.passed]
        note = f"approved — {len(hard)} hard check(s) passed"
        if soft_findings:
            note += f", {len(soft_findings)} soft finding(s) noted"
        return self._result(True, note)
