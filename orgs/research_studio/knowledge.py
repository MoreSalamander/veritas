"""The Research org's "ask without sources" mode — answer from the model's own knowledge, honestly.

The grounded pipeline (build_report) makes YOU supply the corpus — which means you already did the
research. This mode flips that: you ask a question, the model answers from its own knowledge, and the
confidence layer tags each piece so nothing is trusted blindly. It is the INVERSE of grounding —
instead of "ground everything you provide", it answers freely and **flags the uncertain minority**,
which becomes the worklist of what to actually source or human-check.

Nothing here is machine-proven. A Brief is a soft artifact: confident claims are *model-asserted,
unverified* (carrying the disclosed ~6% confident-wrong risk); flagged claims are exactly the ones
the model wobbled or hedged on. See docs/confidence-layer.md and bench/RESULTS.md (2026-06-22).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from engine.model import ModelProvider
from orgs.research_studio.confidence import CONFIDENT, FLAGGED, Confidence, assess

DECOMPOSE_SYSTEM = (
    "Break the user's request into 3 to 6 specific, factual questions whose answers together address "
    "it. Each must have a short, checkable factual answer. Output ONLY the questions, one per line, "
    "no numbering and no other text."
)


@dataclass
class BriefClaim:
    """One sub-question of the request, with its assessed confidence (the answer lives inside it)."""

    question: str
    confidence: Confidence

    @property
    def answer(self) -> str:
        return self.confidence.answer

    @property
    def flagged(self) -> bool:
        return self.confidence.level == FLAGGED


@dataclass
class Brief:
    """The answer to an own-knowledge question: a set of sub-answers, each tagged confident/flagged."""

    question: str
    claims: list[BriefClaim] = field(default_factory=list)

    @property
    def confident(self) -> list[BriefClaim]:
        return [c for c in self.claims if c.confidence.level == CONFIDENT]

    @property
    def flagged(self) -> list[BriefClaim]:
        # the grounding worklist — what the model was unsure of, to source or human-verify
        return [c for c in self.claims if c.confidence.level == FLAGGED]


class KnowledgeAgent:
    role = "knowledge-writer"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def subquestions(self, question: str, max_q: int = 6) -> list[str]:
        raw = self.provider.propose(
            role=self.role, prompt=f"Request: {question}", system=DECOMPOSE_SYSTEM
        )
        out: list[str] = []
        for line in raw.splitlines():
            line = re.sub(r"^\s*[-*\d.)\s]+", "", line).strip()  # strip bullets / numbering
            if line:
                out.append(line)
        return out[:max_q]


def build_brief(
    question: str, provider: ModelProvider, *, samples: int = 5, max_claims: int = 6
) -> Brief:
    """Answer a question from the model's own knowledge: decompose it into checkable sub-questions,
    assess each one's confidence, and assemble a Brief. The flagged claims are the worklist for
    grounding/human-verification. (Cost: a decomposition call + `samples` calls per sub-question.)"""
    agent = KnowledgeAgent(provider)
    subqs = agent.subquestions(question, max_q=max_claims) or [question]
    claims = [BriefClaim(q, assess(provider, q, samples=samples)) for q in subqs]
    return Brief(question=question, claims=claims)
