"""The Research Studio's roster, for the Hub's Org view. Same shape as the other orgs: cast
authored here, gate HARD/SOFT read straight off the gate classes so the page can't drift."""

from __future__ import annotations

from typing import Any

from engine.gate import Gate
from engine.validation import ValidationGate
from orgs.research_studio.gates import (
    CitationsResolveGate,
    ClaimsCitedGate,
    QuotesVerbatimGate,
    ReportScorerGate,
    SupportGate,
)

_CAST: list[tuple[str, str, str]] = [
    ("Researcher", "researcher", "Given a topic and a pinned set of sources, writes a report whose every claim cites a source and quotes it verbatim; re-writes on rejection (e.g. \"misquote of src1\")."),
]

_GATES: list[tuple[type[Gate], str]] = [
    (ReportScorerGate, "the report is structured (parses, has claims) — otherwise nothing to ground"),
    (ClaimsCitedGate, "every claim carries a citation — no naked assertions"),
    (CitationsResolveGate, "every cited source resolves in the pinned corpus — no dangling references"),
    (QuotesVerbatimGate, "every quoted span actually appears, verbatim, in its cited source"),
    (SupportGate, "does the source actually SUPPORT the claim? — an LLM judge, advisory only"),
    (ValidationGate, "final authority: every hard gate passed, provenance complete"),
]


def roster() -> dict[str, Any]:
    return {
        "cast": [{"name": n, "role": r, "produces": p} for n, r, p in _CAST],
        "gates": [
            {"name": g.name, "determinism": g.determinism.value, "scope": "report", "about": about}
            for g, about in _GATES
        ],
        "principle": "A report is verified by GROUNDING, not by being well-written. Every claim "
        "must be attributed, its source must resolve, and its quotes must be real. Whether the "
        "source truly backs the claim is judgment — soft, never a hard guarantee.",
    }
