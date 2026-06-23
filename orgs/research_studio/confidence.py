"""The confidence layer — judging how much to trust a model's own-knowledge answer.

This is the substrate for the Research org's "ask without sources" mode (docs/confidence-layer.md).
It does NOT verify anything against the world — nothing here is machine-proven. It estimates, from
the model's own behaviour, how much an answer should be trusted, and tags it so the UI can show it
honestly and never green.

The rules encode what the measurement actually found (bench/RESULTS.md, 2026-06-22), not intuition:

  * HEDGING is the primary signal. Given permission to say "I don't know", the model consistently
    admits ignorance — so a hedged answer is FLAGGED no matter how consistent it is (the obscure
    unknowns came back at 100% agreement *on a hedge*).
  * LOW SELF-CONSISTENCY is the secondary signal — it catches wrong-but-unhedged answers that wobble
    across samples (it caught a wrong music fact at 75%).
  * "confident" therefore requires BOTH: high agreement AND no hedge. And even then it carries an
    irreducible ~6% confident-wrong rate, which the mode must DISCLOSE — confident is never verified.

A reusable layer kept in research_studio for now; promote to engine/ when a second org needs it
(same "extract on reuse" path the ValidationGate took).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from engine.model import ModelProvider

# Permission to admit ignorance is the whole trick: without it the model confabulates; with it, it
# cleanly hedges the things it doesn't know (measured). Terse answers keep agreement measurable.
HEDGE_SYSTEM = (
    "Answer with ONLY the fact, in as few words as possible. No explanation. "
    "If you are not sure, answer exactly: I don't know."
)

# Self-reported-uncertainty markers. Matched on the normalised answer.
HEDGES = (
    "dont know", "do not know", "not sure", "unsure", "unknown", "cannot", "unable",
    "not available", "no data", "not enough", "unclear", "no idea", "not certain",
)

CONFIDENT = "confident"
FLAGGED = "flagged"


@dataclass
class Confidence:
    """How much to trust one own-knowledge answer. `level` is the verdict; the rest is the evidence
    for it (so the tag is explainable, like every gate result)."""

    level: str          # CONFIDENT | FLAGGED
    answer: str         # the model's modal (most-agreed) answer
    agreement: float    # fraction of samples matching the modal answer (0..1)
    hedged: bool        # did the model self-report uncertainty?
    samples: list[str] = field(default_factory=list)  # the raw normalised draws (transparency)

    @property
    def reason(self) -> str:
        if self.hedged:
            return "flagged — the model said it doesn't know"
        if self.level == FLAGGED:
            return f"flagged — answers disagreed across samples ({self.agreement:.0%} agreement)"
        return f"model-asserted, unverified ({self.agreement:.0%} agreement, no hedge)"


def normalize(text: str) -> str:
    """Reduce a short answer to a comparable form so agreement can be measured. Deliberately light:
    the elicit prompt asks for terse answers, so we only lowercase, take the first line, and strip
    punctuation."""
    line = text.strip().lower().splitlines()[0] if text.strip() else ""
    line = re.sub(r"[^a-z0-9 ]", "", line)
    return re.sub(r"\s+", " ", line).strip()


def is_hedge(answer: str) -> bool:
    """Did the answer self-report uncertainty? Matched on the normalised form."""
    norm = normalize(answer)
    return any(h in norm for h in HEDGES)


def assess(
    provider: ModelProvider,
    question: str,
    *,
    role: str = "knowledge",
    samples: int = 5,
    agreement_floor: float = 0.8,
) -> Confidence:
    """Ask the model the question `samples` times (with permission to hedge) and judge the result.

    CONFIDENT iff the answers agree at/above the floor AND none hedged; otherwise FLAGGED. This is
    a confidence estimate from the model's own behaviour — never a check against truth, so the result
    is only ever a soft tag, and even CONFIDENT carries the disclosed ~6% confident-wrong risk."""
    draws = [normalize(provider.propose(role=role, prompt=question, system=HEDGE_SYSTEM))
             for _ in range(max(1, samples))]
    hedged = any(any(h in d for h in HEDGES) for d in draws)
    counts = Counter(d for d in draws if d)
    answer, top = (counts.most_common(1)[0] if counts else ("", 0))
    agreement = top / len(draws)
    level = CONFIDENT if (agreement >= agreement_floor and not hedged) else FLAGGED
    return Confidence(level=level, answer=answer, agreement=agreement, hedged=hedged, samples=draws)
