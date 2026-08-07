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


# The relationship vocabulary is closed: a typed edge either uses a known
# relation or the parser refuses it. Free-text relations would turn the
# context graph into prose wearing a graph costume.
RELATIONS = (
    "supports", "contradicts", "depends_on", "causes",
    "enables", "improves", "competes_with", "introduced_by", "related_to",
)


@dataclass
class Entity:
    """A named thing the research surfaced: person, company, technology,
    concept, paper, product — typed and described, never bare."""

    name: str
    type: str = "concept"
    description: str = ""


@dataclass
class Relationship:
    """A typed edge between two surfaced entities. `claim_index` optionally
    anchors the edge to the claim that evidences it — anchored edges are
    checkable; unanchored ones are honest proposals."""

    source: str
    relation: str
    target: str
    claim_index: int | None = None


@dataclass
class Report:
    topic: str
    claims: list[Claim]
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)


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

    entities: list[Entity] = []
    for i, re_ in enumerate(obj.get("entities") or []):
        if not isinstance(re_, dict) or not isinstance(re_.get("name"), str) or not re_["name"].strip():
            raise ReportParseError(f"entity {i} missing non-empty 'name'")
        entities.append(Entity(
            name=re_["name"].strip(),
            type=str(re_.get("type") or "concept").strip() or "concept",
            description=str(re_.get("description") or "").strip(),
        ))

    known = {e.name for e in entities}
    relationships: list[Relationship] = []
    for i, rr in enumerate(obj.get("relationships") or []):
        if not isinstance(rr, dict):
            raise ReportParseError(f"relationship {i} must be an object")
        src, rel, tgt = rr.get("source"), rr.get("relation"), rr.get("target")
        if not (isinstance(src, str) and src.strip() and isinstance(tgt, str) and tgt.strip()):
            raise ReportParseError(f"relationship {i} missing 'source'/'target'")
        if rel not in RELATIONS:
            raise ReportParseError(
                f"relationship {i} relation {rel!r} not in the vocabulary {RELATIONS}"
            )
        if src.strip() not in known or tgt.strip() not in known:
            raise ReportParseError(
                f"relationship {i} references an undeclared entity — every edge "
                f"endpoint must appear in 'entities'"
            )
        ci = rr.get("claim_index")
        if ci is not None and (not isinstance(ci, int) or not (0 <= ci < len(claims))):
            raise ReportParseError(f"relationship {i} claim_index {ci!r} out of range")
        relationships.append(Relationship(
            source=src.strip(), relation=str(rel), target=tgt.strip(), claim_index=ci,
        ))

    open_questions = [
        str(q).strip() for q in (obj.get("open_questions") or []) if str(q).strip()
    ]

    return Report(
        topic=str(obj.get("topic", "")),
        claims=claims,
        entities=entities,
        relationships=relationships,
        open_questions=open_questions,
    )


# Typographic variants that must NOT decide a verbatim match. Sources (especially from the web) use
# curly quotes/apostrophes, en/em dashes, and ellipsis characters that a model routinely re-types as
# their ASCII forms (or vice versa). Folding these keeps the gate strict on the WORDS — a paraphrase
# still fails — while not rejecting an exact copy over punctuation style. (Same intent as the
# whitespace fold: formatting shouldn't decide truth.)
_TYPOGRAPHY = str.maketrans({
    "“": '"', "”": '"',                 # “ ”  curly double quotes
    "‘": "'", "’": "'",                 # ‘ ’  curly single quotes / apostrophe
    "′": "'", "″": '"',                 # ′ ″  primes
    "–": "-", "—": "-", "―": "-",  # – — ―  dashes
    "…": "...",                              # …  ellipsis
})


def normalize(text: str) -> str:
    """Whitespace- and typography-insensitive form for verbatim matching — smart quotes, dashes and
    ellipses shouldn't decide truth; the WORDS still must match exactly, so a paraphrase still fails."""
    return " ".join(text.translate(_TYPOGRAPHY).split())


def render_markdown(report: Report, source_urls: dict[str, str] | None = None) -> str:
    """The human face of a verified report.

    The artifact the gates rule on is deliberately machine-shaped — claims and
    citations as JSON — so verification is exact. Nobody should have to READ
    that. This renders the verified structure as a normal research page:
    findings with their citation marks, the verbatim quotes each claim leans
    on, and a sources index. Deterministic: the same report and URL map always
    produce the same page, so the rendering adds nothing the gates didn't rule
    on. `source_urls` maps corpus ids (src1, ...) to where each source came
    from; ids without a URL are labeled as pinned corpus text.
    """
    urls = source_urls or {}
    lines: list[str] = [f"# {report.topic}", "", "## Findings", ""]
    for claim in report.claims:
        marks = "".join(f" [{c.source}]" for c in claim.citations)
        lines.append(f"- {claim.text}{marks}")
        for cit in claim.citations:
            if cit.quote:
                lines.append(f'> "{cit.quote}" — {cit.source}')
        lines.append("")
    if report.entities:
        lines += ["## Entities", ""]
        for ent in report.entities:
            desc = f" — {ent.description}" if ent.description else ""
            lines.append(f"- **{ent.name}** ({ent.type}){desc}")
        lines.append("")
    if report.relationships:
        lines += ["## Research map", ""]
        for rel in report.relationships:
            anchor = f" [src-claim {rel.claim_index + 1}]" if rel.claim_index is not None else " (proposed)"
            lines.append(f"- {rel.source} —{rel.relation.replace('_', ' ')}→ {rel.target}{anchor}")
        lines.append("")
    if report.open_questions:
        lines += ["## Open questions", ""]
        for q in report.open_questions:
            lines.append(f"- {q}")
        lines.append("")
    cited = sorted(
        {c.source for claim in report.claims for c in claim.citations},
        key=lambda s: (len(s), s),  # src2 before src10
    )
    if cited:
        lines += ["## Sources", ""]
        for sid in cited:
            lines.append(f"- [{sid}] {urls.get(sid, 'pinned corpus text (provided to the run)')}")
    return "\n".join(lines).strip() + "\n"
