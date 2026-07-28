"""Grounding check on institutional memory — Python verification that a MemoryRecord
stays anchored to whatever it claims informed it.

Every org's own gates already verify an artifact's *content* at build time (a Research
report's citations, a Software module's tests). What those gates don't check is a
narrower, second-brain-specific claim: `informed_by` on a record's provenance says
"this build read these past lessons/decisions before it acted" (see
`engine/memory.py`'s `format_lessons`) — but nothing has ever verified that the new
record actually stayed anchored to what it claims informed it, rather than the
`informed_by` list being stale, copy-pasted, or simply wrong. That's the same shape of
risk myAIstro's grounding checks (verifying LLM-generated study-guide text against its
source lesson) defend against, aimed one level up: not "is the artifact correct" but
"does the org's own memory trail actually hold together."

Two complementary checks, mirroring the same split as prompt/text and code:

  check_text_grounding — substantial tokens (4+ chars, alphanumeric, not stopwords) in
                         a record's body checked against the concatenated body of the
                         records it claims informed it. A rough "did this actually
                         draw on what it says it drew on" ratio.

  check_code_grounding — backticked/fenced code in a record's body checked against
                         that same source text. Code drift is the highest-confidence
                         signal of a stale or fabricated `informed_by` link.

Both return a report dict with `ratio` (0.0-1.0) and a small sample of ungrounded
items for diagnostic surfacing in the UI. This is diagnostic, not gating: it never
blocks a record from persisting (the org's own gates already did that verification
at build time) — it only tells a human whether the memory trail is honest.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from engine.memory import MemoryRecord, MemoryStore

# Matches validation_agent.py's LOOSE_TOKEN_MIN convention.
LOOSE_TOKEN_MIN = 4

TOKEN_STOPWORDS = {
    "this", "that", "these", "those", "what", "when", "where", "which",
    "would", "could", "should", "their", "they", "them", "your", "ours",
    "with", "from", "into", "onto", "than", "then", "also", "such",
    "about", "after", "before", "between", "under", "above", "below",
    "over", "through", "during", "while", "because", "even", "still",
    "have", "make", "made", "take", "took", "give", "gave", "come", "came",
    "want", "need", "like", "used", "using", "based", "called",
    "more", "most", "some", "many", "much", "very", "well", "only", "just",
    "back", "down", "same", "other", "another", "each", "every", "both",
    "thing", "things", "stuff", "part", "parts", "side", "case", "cases",
    "time", "times", "way", "ways", "kind", "sort", "type", "types",
}


def check_text_grounding(text: str, source_text: str) -> Dict[str, Any]:
    """Return a grounding report for `text` against `source_text`. Empty text -> ratio
    1.0 (nothing to be wrong about). Non-empty text with no source -> ratio 0.0."""
    tokens = _extract_substantial_tokens(text)
    if not tokens:
        return {"kind": "text", "total_tokens": 0, "grounded_tokens": 0,
                "ratio": 1.0, "ungrounded_sample": []}

    src_lower = source_text.lower() if source_text else ""
    if not src_lower:
        return {"kind": "text", "total_tokens": len(tokens), "grounded_tokens": 0,
                "ratio": 0.0, "ungrounded_sample": _dedupe_first_n(tokens, 10)}

    grounded = 0
    ungrounded: List[str] = []
    for t in tokens:
        if t in src_lower:
            grounded += 1
        else:
            ungrounded.append(t)

    total = len(tokens)
    return {
        "kind": "text",
        "total_tokens": total,
        "grounded_tokens": grounded,
        "ratio": round(grounded / total, 3) if total else 1.0,
        "ungrounded_sample": _dedupe_first_n(ungrounded, 10),
    }


def check_code_grounding(text: str, source_text: str) -> Dict[str, Any]:
    """Snippet-level grounding for backticked/fenced code inside `text`."""
    if not text:
        return {"kind": "code", "total_snippets": 0, "grounded_snippets": 0,
                "ratio": 1.0, "ungrounded_sample": []}

    inline = re.findall(r"`([^`\n]+)`", text)
    fenced = re.findall(r"```[\w-]*\n(.*?)```", text, re.DOTALL)
    snippets = [s for s in (inline + fenced) if s.strip()]
    if not snippets:
        return {"kind": "code", "total_snippets": 0, "grounded_snippets": 0,
                "ratio": 1.0, "ungrounded_sample": []}

    src_lower = (source_text or "").lower()
    if not src_lower:
        return {"kind": "code", "total_snippets": len(snippets), "grounded_snippets": 0,
                "ratio": 0.0, "ungrounded_sample": [_preview(s) for s in snippets[:5]]}

    grounded = 0
    ungrounded: List[str] = []
    for snippet in snippets:
        s = snippet.strip().lower()
        if s in src_lower:
            grounded += 1
            continue
        lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
        if lines and sum(1 for ln in lines if ln in src_lower) * 2 >= len(lines):
            grounded += 1
            continue
        ungrounded.append(snippet)

    total = len(snippets)
    return {
        "kind": "code",
        "total_snippets": total,
        "grounded_snippets": grounded,
        "ratio": round(grounded / total, 3) if total else 1.0,
        "ungrounded_sample": [_preview(s) for s in ungrounded[:5]],
    }


def combined_report(text: str, source_text: str) -> Dict[str, Any]:
    text_report = check_text_grounding(text, source_text)
    code_report = check_code_grounding(text, source_text)
    return {
        "text": text_report,
        "code": code_report,
        "overall_ratio": round(0.7 * text_report["ratio"] + 0.3 * code_report["ratio"], 3),
    }


def record_grounding(record: "MemoryRecord", store: "MemoryStore") -> Dict[str, Any] | None:
    """Grounding report for one record against the records its own provenance claims
    informed it (`informed_by`). Returns None when a record makes no such claim —
    there's nothing to check for a record that doesn't cite its own memory trail."""
    informed_by = record.provenance.get("informed_by") or []
    if not informed_by:
        return None
    wanted = set(informed_by)
    sources = [r for r in store.load_all() if r.id in wanted]
    if not sources:
        # The record claims an informed_by trail that resolves to nothing still on file —
        # that's the most honest possible "ungrounded" signal, worth surfacing as such
        # rather than silently returning None.
        return {**combined_report(record.body, ""), "missing_sources": sorted(wanted)}
    source_text = "\n\n".join(s.body for s in sources)
    return combined_report(record.body, source_text)


def _extract_substantial_tokens(text: str) -> List[str]:
    if not text:
        return []
    raw = re.findall(rf"[a-zA-Z][a-zA-Z0-9_]{{{LOOSE_TOKEN_MIN - 1},}}", text)
    return [r.lower() for r in raw if r.lower() not in TOKEN_STOPWORDS]


def _dedupe_first_n(items: List[str], n: int) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
        if len(out) >= n:
            break
    return out


def _preview(snippet: str, max_len: int = 60) -> str:
    first_line = snippet.strip().split("\n", 1)[0]
    return (first_line[: max_len - 1] + "…") if len(first_line) > max_len else first_line
