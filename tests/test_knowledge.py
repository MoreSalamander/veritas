"""The Research org's "ask without sources" mode — answer from knowledge, flag the uncertain.

Offline with a SequencedProvider (different answer per call) so a brief with one confident and one
flagged claim is exercised deterministically. Call order: one decomposition call ("knowledge-writer"),
then `samples` assess calls ("knowledge") per sub-question, in order.
"""

from __future__ import annotations

from engine.model import ScriptedProvider, SequencedProvider
from orgs.research_studio.knowledge import Brief, build_brief


def test_brief_splits_confident_from_flagged_worklist():
    provider = SequencedProvider({
        # decompose the request into two checkable sub-questions
        "knowledge-writer": ["Where was the artist born?\nWhat was the artist's debut single?"],
        # 2 samples x 2 sub-questions: Q1 agrees (confident), Q2 wobbles (flagged)
        "knowledge": ["new york", "new york", "wet leg", "chaise longue"],
    })
    brief = build_brief("tell me about the artist", provider, samples=2)
    assert isinstance(brief, Brief) and len(brief.claims) == 2
    assert [c.question for c in brief.confident] == ["Where was the artist born?"]
    assert [c.question for c in brief.flagged] == ["What was the artist's debut single?"]
    # the flagged list is the grounding worklist
    assert brief.flagged[0].confidence.agreement < 0.8


def test_brief_flags_a_hedged_sub_question():
    provider = SequencedProvider({
        "knowledge-writer": ["What is the capital?\nWhat is the obscure detail?"],
        "knowledge": ["tokyo", "tokyo", "i dont know", "i dont know"],  # Q2 consistently hedged
    })
    brief = build_brief("a request", provider, samples=2)
    flagged = brief.flagged
    assert [c.question for c in flagged] == ["What is the obscure detail?"]
    assert flagged[0].confidence.hedged  # flagged because the model admitted it doesn't know


def test_brief_falls_back_to_the_question_when_decomposition_is_empty():
    provider = ScriptedProvider({"knowledge-writer": "", "knowledge": "tokyo"})
    brief = build_brief("capital of Japan?", provider, samples=3)
    assert len(brief.claims) == 1 and brief.claims[0].question == "capital of Japan?"
    assert brief.confident  # the single answer was consistent
