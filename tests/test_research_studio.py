"""P16a — the Research Studio spine: a report is verified by grounding.

No LLM, no judgment — every check is a fact about the report against a pinned corpus. A grounded
report clears the floor; each mutant (a naked claim, a dangling citation, a misquote, junk) trips
exactly the gate that owns its defect. The grounding analogue of test_spine / test_web_studio.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from orgs.research_studio.gates import (
    CitationsResolveGate,
    ClaimsCitedGate,
    QuotesVerbatimGate,
    ReportScorerGate,
)

CORPUS = {
    "src1": "The bald eagle is a bird of prey native to North America. Bald eagles can fly at "
            "speeds of up to 30 mph and dive at over 100 mph.",
    "src2": "A bald eagle's nest can weigh more than a ton, the largest of any North American bird.",
}

GOOD = json.dumps({
    "topic": "bald eagles",
    "claims": [
        {"text": "Bald eagles can fly up to 30 mph",
         "citations": [{"source": "src1", "quote": "fly at speeds of up to 30 mph"}]},
        {"text": "Their nests can weigh over a ton",
         "citations": [{"source": "src2", "quote": "nest can weigh more than a ton"}]},
    ],
})


def _report(payload: str) -> Artifact:
    return Artifact.propose(type="report", owner="test", payload=payload, rationale="test")


def test_grounded_report_clears_the_floor():
    a = _report(GOOD)
    assert ReportScorerGate().check(a).passed
    assert ClaimsCitedGate().check(a).passed
    assert CitationsResolveGate(CORPUS).check(a).passed
    assert QuotesVerbatimGate(CORPUS).check(a).passed


def test_prose_is_rejected_by_the_scorer():
    res = ReportScorerGate().check(_report("Bald eagles are majestic. (no JSON, no claims.)"))
    assert not res.passed and "not usable" in res.evidence


def test_naked_claim_fails_every_claim_cited():
    bad = json.dumps({"topic": "x", "claims": [
        {"text": "Bald eagles can fly up to 30 mph", "citations": [{"source": "src1", "quote": "fly at speeds of up to 30 mph"}]},
        {"text": "Bald eagles are the strongest birds alive", "citations": []},
    ]})
    res = ClaimsCitedGate().check(_report(bad))
    assert not res.passed and "uncited" in res.evidence


def test_dangling_citation_fails_resolve():
    bad = json.dumps({"topic": "x", "claims": [
        {"text": "Something", "citations": [{"source": "src9", "quote": ""}]}]})
    res = CitationsResolveGate(CORPUS).check(_report(bad))
    assert not res.passed and "src9" in res.evidence


def test_misquote_fails_verbatim():
    bad = json.dumps({"topic": "x", "claims": [
        {"text": "Bald eagles fly at 500 mph",
         "citations": [{"source": "src1", "quote": "fly at speeds of up to 500 mph"}]}]})
    res = QuotesVerbatimGate(CORPUS).check(_report(bad))
    assert not res.passed and "misquote" in res.evidence


def test_quote_matching_is_whitespace_insensitive():
    # the same words, reformatted, still count as verbatim — formatting doesn't decide truth
    spaced = json.dumps({"topic": "x", "claims": [
        {"text": "speed", "citations": [{"source": "src1", "quote": "fly   at speeds\nof up to 30 mph"}]}]})
    assert QuotesVerbatimGate(CORPUS).check(_report(spaced)).passed


def test_quote_matching_is_typography_insensitive():
    # the source uses curly quotes and an em-dash; the model re-typed them as ASCII. Same WORDS, so
    # it's still verbatim — typography shouldn't decide truth (this is what failed the gto-poker runs).
    corpus = {"src1": "Balance is the foundation of GTO — you must “mix” your play."}
    ascii_copy = json.dumps({"topic": "x", "claims": [
        {"text": "mixing", "citations": [{"source": "src1",
         "quote": 'foundation of GTO - you must "mix" your play'}]}]})
    assert QuotesVerbatimGate(corpus).check(_report(ascii_copy)).passed
    # but a real PARAPHRASE (different words) still fails — only typography is folded, not meaning
    paraphrase = json.dumps({"topic": "x", "claims": [
        {"text": "mixing", "citations": [{"source": "src1",
         "quote": "balance is central so you should vary your play"}]}]})
    assert not QuotesVerbatimGate(corpus).check(_report(paraphrase)).passed
