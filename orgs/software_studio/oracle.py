"""P13d — the voting oracle: graded confidence for the value gap properties can't reach.

Some value errors have no oracle-free relation to catch them (nothing structural separates
`a+b` from `a-b`). For those, P13b left the exact-value check SOFT, trusting one model's
number as advice. This strengthens that soft signal WITHOUT pretending it is certainty.

The move: re-derive the expected output INDEPENDENTLY several times — multiple samples and/or
multiple models — and measure how much they agree. Independent slips rarely land on the same
wrong answer, so agreement filters out random hallucination and raises confidence.

It stays SOFT on purpose. Cross-model agreement is *correlated*: models trained on overlapping
data share the same misconceptions, so unanimous agreement on a wrong-but-popular answer is
indistinguishable from agreement on truth. Agreement raises confidence, never certainty — the
only path to a HARD value check is an independent second *method* (differential testing), not
more votes from the same kind of guesser. So this reports a graded confidence the build can act
on (drive a retry, flag a human, rank implementations) but it never accepts on its own.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from engine.model import ModelProvider

ORACLE_SYSTEM = (
    "You independently compute the single correct output of a function. Given its name, "
    "description, and the argument list, reply with ONLY a JSON object {\"value\": <the "
    "correct output>}. No prose, no explanation, no code."
)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a == b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return bool(a == b)


def parse_value(text: str) -> tuple[bool, Any]:
    """Pull {"value": x} out of a model reply. Returns (ok, value); (False, None) on
    anything malformed — an undrawable oracle simply doesn't get a vote."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return False, None
    try:
        obj = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return False, None
    if isinstance(obj, dict) and "value" in obj:
        return True, obj["value"]
    return False, None


@dataclass
class VoteResult:
    consensus: Any            # the value the most draws agreed on (None if no valid draws)
    agreement: float          # fraction of valid draws matching the consensus (0.0–1.0)
    total: int                # number of valid (parseable) draws
    tally: dict[str, int] = field(default_factory=dict)  # value-string -> count, for evidence

    def confidence(self) -> str:
        if self.total == 0:
            return "none"
        if self.total >= 2 and self.agreement >= 0.999:
            return "high"
        if self.agreement >= 0.6:
            return "moderate"
        return "low"


class VotingOracle:
    """Re-derives a function's output for given args across N independent draws (each provider
    sampled `samples` times) and reports the consensus + how strongly the draws agreed."""

    def __init__(self, providers: list[ModelProvider], samples: int = 1) -> None:
        if not providers or samples < 1:
            raise ValueError("VotingOracle needs at least one provider and samples >= 1")
        self.providers = providers
        self.samples = samples

    def vote(self, *, function_name: str, description: str, args: list[Any]) -> VoteResult:
        prompt = (
            f"Function: {function_name}\nDescription: {description}\n"
            f"Arguments (positional): {json.dumps(args)}\n"
            "What is the correct output?"
        )
        draws: list[Any] = []
        for provider in self.providers:
            for _ in range(self.samples):
                try:
                    raw = provider.propose(role="oracle", prompt=prompt, system=ORACLE_SYSTEM)
                except Exception:
                    continue
                ok, value = parse_value(raw)
                if ok:
                    draws.append(value)

        if not draws:
            return VoteResult(consensus=None, agreement=0.0, total=0)

        # Cluster by float-aware equality: the consensus is the value the most draws match.
        best_value: Any = draws[0]
        best_count = 0
        for candidate in draws:
            count = sum(1 for d in draws if _eq(d, candidate))
            if count > best_count:
                best_count, best_value = count, candidate

        tally: dict[str, int] = {}
        for d in draws:
            tally[str(d)] = tally.get(str(d), 0) + 1

        return VoteResult(
            consensus=best_value,
            agreement=best_count / len(draws),
            total=len(draws),
            tally=tally,
        )
