"""The confidence layer — judging trust in an own-knowledge answer (no source grounding).

Driven offline with a SequencedProvider (different answer per call) so the three behaviours the
measurement found — confident, flagged-by-hedge, flagged-by-disagreement — are exercised
deterministically, with no model running.
"""

from __future__ import annotations

from engine.model import ScriptedProvider, SequencedProvider
from orgs.research_studio.confidence import (
    CONFIDENT,
    FLAGGED,
    assess,
    is_hedge,
    normalize,
)


def test_normalize_makes_short_answers_comparable():
    assert normalize("Mars.") == normalize("  mars\nthe red planet") == "mars"
    assert normalize("1969") == "1969"


def test_is_hedge_detects_self_reported_uncertainty():
    assert is_hedge("I don't know")
    assert is_hedge("Unknown — not enough data")
    assert not is_hedge("Tokyo")


def test_confident_when_consistent_and_unhedged():
    # the model says the same thing every time, no hedge -> confident (but still only model-asserted)
    prov = ScriptedProvider({"knowledge": "Tokyo"})
    c = assess(prov, "capital of Japan?", samples=5)
    assert c.level == CONFIDENT and c.answer == "tokyo" and c.agreement == 1.0 and not c.hedged
    assert "unverified" in c.reason  # never claims to be verified


def test_flagged_by_hedge_even_at_full_agreement():
    # the model CONSISTENTLY says "I don't know" — high agreement, but a hedge must flag it.
    prov = ScriptedProvider({"knowledge": "I don't know"})
    c = assess(prov, "attendance of an obscure match?", samples=5)
    assert c.hedged and c.level == FLAGGED and c.agreement == 1.0  # consistency doesn't override a hedge
    assert "doesn't know" in c.reason


def test_flagged_by_disagreement_when_answers_wobble():
    # answers scatter across samples -> low agreement -> flagged (the secondary signal)
    prov = SequencedProvider({"knowledge": ["wet leg", "wet willing", "chaise longue", "wet leg"]})
    c = assess(prov, "Wet Leg debut single?", samples=4)
    assert not c.hedged and c.agreement < 0.8 and c.level == FLAGGED


def test_high_agreement_but_wrong_still_ships_confident_the_disclosed_blind_spot():
    # the ~6% case: the model is consistent AND unhedged AND wrong. The layer CANNOT catch this — it
    # ships CONFIDENT (model-asserted), which is exactly why "confident" is never shown as verified.
    prov = ScriptedProvider({"knowledge": "2"})  # black midi: actually 3
    c = assess(prov, "how many albums had black midi released by 2023?", samples=5)
    assert c.level == CONFIDENT  # the honest limit, encoded as a test
