"""The admission gate — one recursive level up from each source's own gate.

This does NOT re-judge the domain claim (it never re-decides whether a given
opportunity is actually legit, whether a lesson is well-formed, etc. — that
judgment already happened, and belongs to, the source's own deterministic
gate). It verifies only that *crossing the boundary* into Entropy's own
store was legitimate: does the evidence copied from the source exist and
parse into the shape every source's own verification is supposed to carry.
"""

from __future__ import annotations

from dataclasses import dataclass

from .records import EntropyRecord


@dataclass(frozen=True)
class StructuralVerdict:
    passed: bool
    reason: str


def check_structural(record: EntropyRecord) -> StructuralVerdict:
    if not record.source_ref.strip():
        return StructuralVerdict(False, "empty source_ref")
    if not record.verification:
        return StructuralVerdict(False, "no verification evidence copied from source")
    for i, ev in enumerate(record.verification):
        if not isinstance(ev, dict) or "check" not in ev or "passed" not in ev:
            return StructuralVerdict(False, f"verification[{i}] missing check/passed shape")
        if not isinstance(ev["check"], str) or not isinstance(ev["passed"], bool):
            return StructuralVerdict(False, f"verification[{i}] wrong types for check/passed")
    # A record whose own verification says passed=False can still pass THIS
    # gate — that's an honestly-collected "rejected by the source" record,
    # structurally sound. Whether it should also be auto-admitted is a
    # default_trust policy question, not this check's to make.
    return StructuralVerdict(True, "structural check passed")
