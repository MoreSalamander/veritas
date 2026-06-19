"""P16 — the Research Studio's artifact: a grounded report.

A report is not prose to be admired — it is a set of *claims*, each backed by *citations* into
a pinned source corpus. That structure is what makes "done" a fact instead of a taste: a claim
is trustworthy when it is attributed, its source resolves, and the words it quotes actually
appear there. The corpus is pinned (given, not fetched live) so verification is reproducible —
the same report + corpus always yields the same verdict.

The semantic question — does the source *actually support* the claim — is judgment, and stays
SOFT (see the support gate). Everything here is the deterministic floor under it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# A pinned corpus: source id -> full source text. Citations resolve against this.
Corpus = dict[str, str]


class ReportParseError(ValueError):
    """The proposed report is not usable. The report-scorer rejects on this."""


@dataclass
class Citation:
    source: str  # a source id that must resolve in the corpus
    quote: str = ""  # an optional verbatim span that must appear in that source


@dataclass
class Claim:
    text: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class Report:
    topic: str
    claims: list[Claim]


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ReportParseError("no JSON object found in report output")
    return text[start : end + 1]


def parse_report(payload: str) -> Report:
    try:
        obj: Any = json.loads(_extract_json(payload))
    except (ValueError, TypeError) as exc:
        raise ReportParseError(f"report is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ReportParseError("report must be a JSON object")

    raw_claims = obj.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ReportParseError("report has no claims (nothing to ground)")

    claims: list[Claim] = []
    for i, rc in enumerate(raw_claims):
        if not isinstance(rc, dict) or not isinstance(rc.get("text"), str) or not rc["text"].strip():
            raise ReportParseError(f"claim {i} missing non-empty 'text'")
        raw_cites = rc.get("citations", [])
        if not isinstance(raw_cites, list):
            raise ReportParseError(f"claim {i} 'citations' must be a list")
        cites: list[Citation] = []
        for j, cc in enumerate(raw_cites):
            if not isinstance(cc, dict) or not isinstance(cc.get("source"), str) or not cc["source"].strip():
                raise ReportParseError(f"claim {i} citation {j} missing 'source'")
            quote = cc.get("quote", "")
            cites.append(Citation(source=cc["source"].strip(), quote=str(quote)))
        claims.append(Claim(text=rc["text"].strip(), citations=cites))

    return Report(topic=str(obj.get("topic", "")), claims=claims)


def normalize(text: str) -> str:
    """Whitespace-insensitive form for verbatim matching — formatting shouldn't decide truth."""
    return " ".join(text.split())
