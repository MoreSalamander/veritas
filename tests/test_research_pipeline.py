"""P16b — the Research Studio pipeline: topic + sources -> a grounded report, end to end.

Offline (ScriptedProvider): a grounded report ships through the grounding gates; a misquote is
HARD-rejected; and a claim the judge calls unsupported still ships (the hard floor — cited,
resolves, verbatim — is met) but is flagged SOFT. The hard/soft split, in the grounding domain.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.research_studio.pipeline import build_report

CORPUS = {
    "src1": "The bald eagle is native to North America. Bald eagles can fly at speeds of up to 30 mph.",
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
MISQUOTE = json.dumps({
    "topic": "bald eagles",
    "claims": [{"text": "Bald eagles fly at 500 mph",
                "citations": [{"source": "src1", "quote": "fly at speeds of up to 500 mph"}]}],
})
JUDGE_OK = json.dumps([{"index": 0, "verdict": "SUPPORTED"}, {"index": 1, "verdict": "SUPPORTED"}])
JUDGE_FLAGS = json.dumps([{"index": 0, "verdict": "UNSUPPORTED"}, {"index": 1, "verdict": "SUPPORTED"}])


def test_grounded_report_ships(tmp_path):
    provider = ScriptedProvider({"researcher": GOOD, "judge": JUDGE_OK})
    res = build_report("bald eagles", CORPUS, provider, MemoryStore(tmp_path))
    assert res.accepted
    names = [g.gate_name for g in res.report_outcome.artifact.provenance.gate_results]
    assert names == ["report-scorer", "every-claim-cited", "citations-resolve",
                     "quotes-verbatim", "support", "validation"]
    assert res.report_outcome.memory_path.parent.name == "institutional"


def test_misquote_is_hard_rejected(tmp_path):
    provider = ScriptedProvider({"researcher": MISQUOTE, "judge": JUDGE_OK})
    res = build_report("bald eagles", CORPUS, provider, MemoryStore(tmp_path))
    assert not res.accepted
    vq = next(g for g in res.report_outcome.artifact.provenance.gate_results if g.gate_name == "quotes-verbatim")
    assert not vq.passed and "misquote" in vq.evidence


def test_unsupported_claim_ships_but_is_flagged_soft(tmp_path):
    # the hard floor (cited / resolves / verbatim) is met, so it ships — but the judge's doubt
    # is recorded as an advisory, never laundered into a hard guarantee.
    provider = ScriptedProvider({"researcher": GOOD, "judge": JUDGE_FLAGS})
    res = build_report("bald eagles", CORPUS, provider, MemoryStore(tmp_path))
    assert res.accepted
    support = next(g for g in res.report_outcome.artifact.provenance.gate_results if g.gate_name == "support")
    assert support.determinism.value == "soft" and not support.passed
    assert "unsupported" in support.evidence
