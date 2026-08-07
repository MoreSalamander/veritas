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
    VouchedAttributionGate,
)

_CAST: list[tuple[str, str, str]] = [
    ("Planner", "researcher", "Charts the research: domain, questions, and which angles to send workers down — proposed as JSON, accepted only by the deterministic plan parser (closed angle vocabulary)."),
    ("Angle Workers", "acquisition", "One deterministic worker per planned angle (academic, industry, news, code, patents, market, community, history, regulation, documentation) fetching live sources in parallel; every source lands tagged with the angle that found it."),
    ("Researcher", "researcher", "Given the pinned corpus, extracts claims (every one cited, quotes verbatim) AND the research graph — typed entities and relationships plus open questions; re-writes on rejection (e.g. \"misquote of src1\")."),
    ("The Knowledge Layer", "memory", "Verified entities and relationships persist to org memory; the next run on nearby ground starts briefed with what the org already knows."),
]

_GATES: list[tuple[type[Gate], str]] = [
    (ReportScorerGate, "the report is structured (parses, has claims) — otherwise nothing to ground"),
    (ClaimsCitedGate, "every claim carries a citation — no naked assertions"),
    (CitationsResolveGate, "every cited source resolves in the pinned corpus — no dangling references"),
    (QuotesVerbatimGate, "every quoted span actually appears, verbatim, in its cited source"),
    (VouchedAttributionGate, "a claim leaning on a human-vouched (Knowledge Graph) source must ATTRIBUTE it, not state it as fact — unverified material can't be laundered into grounded truth"),
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
