"""P28c1 — the containment under consumption: the Second Brain may inform Research, but it can
never be laundered into grounded fact.

A human-vouched (commons) source is UNVERIFIED — the human vouched it is worth keeping, not that
its claims are true. So the verbatim-quote gate is not enough: it passes a quote whether the claim
attributes the source ("Source X states Y") or asserts it as fact ("Y is true"). VouchedAttribution
draws that line. The crux test below changes NOTHING but the framing of the claim — same source,
same verbatim quote — and watches a pass become a refusal.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.research_studio.gates import VouchedAttributionGate
from orgs.research_studio.pipeline import build_report

VOUCHED = {"commons:vid": "Rick Astley"}  # a commons source id -> its attribution label
CORPUS = {"commons:vid": "the sky is green"}


def _report(claim_text: str, source: str = "commons:vid") -> Artifact:
    payload = json.dumps(
        {
            "topic": "the sky",
            "claims": [
                {"text": claim_text, "citations": [{"source": source, "quote": "the sky is green"}]}
            ],
        }
    )
    return Artifact.propose(type="report", owner="t", payload=payload, rationale="t")


def test_only_difference_is_framing_attributed_passes_factual_refuses():
    gate = VouchedAttributionGate(VOUCHED)
    # Identical citation, identical verbatim quote — the ONLY difference is attribution.
    attributed = gate.check(_report("According to Rick Astley, the sky is green."))
    factual = gate.check(_report("The sky is green."))
    assert attributed.passed is True
    assert factual.passed is False
    assert "attribute" in factual.evidence.lower()


def test_verified_tier_sources_are_untouched_by_the_gate():
    # A source NOT in `vouched` is verified-tier; a bare factual claim citing it is fine.
    gate = VouchedAttributionGate(VOUCHED)
    res = gate.check(_report("The sky is green.", source="peer_reviewed_paper"))
    assert res.passed is True


def test_pipeline_accepts_attributed_and_keeps_vouched_provenance(tmp_path):
    provider = ScriptedProvider({"researcher": _report("According to Rick Astley, the sky is green.").payload})
    res = build_report("the sky", CORPUS, provider, MemoryStore(tmp_path), vouched=VOUCHED)
    assert res.accepted
    # the unverified provenance travels with the run
    assert "commons:vid" in res.informed_by


def test_pipeline_refuses_factual_grounding_on_a_vouched_source(tmp_path):
    provider = ScriptedProvider({"researcher": _report("The sky is green.").payload})
    res = build_report("the sky", CORPUS, provider, MemoryStore(tmp_path), vouched=VOUCHED)
    assert not res.accepted
