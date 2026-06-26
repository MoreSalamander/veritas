"""Prompt tuning — change a proposer prompt only when a reproducible accept-rate A/B says it's better.

This is the prompt studio's engine. The measurement (`bench/promptbench.py`, recorded in
`bench/RESULTS.md`) proved two things: a proposer-prompt change *does* move the verified bar, and a
human-"cosmetic" reword can be a 67-point regression — so prompt intuition is unreliable. The
conclusion is the reflexive rule (README §4.5) applied to prompts: a candidate prompt is never
trusted because it *looks* better, only because it *clears more of a goal suite's HARD gates* than the
prompt in use. This runs exactly that A/B and reports who won; it judges nothing on looks.

Honest scope — overfitting is the trap. The verdict is over whatever suite you pass. Scoring a
candidate on the very goals it was written against is the prompt analogue of judge collusion (teaching
to the test). A real improvement is one that reproduces on a **held-out** suite the prompt's author
didn't see; the caller owns that split, and `improved` is only meaningful relative to it.
"""

from __future__ import annotations

import pathlib
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

from engine.memory import MemoryStore
from engine.model import ModelProvider
from orgs.software_studio import agents
from orgs.software_studio.builder import build

# A factory so every build gets a fresh provider (clean model state), exactly as the bench does.
ProviderFactory = Callable[[], ModelProvider]


@contextmanager
def spec_system(text: str) -> Iterator[None]:
    """Temporarily run the org with a different Spec proposer prompt. The injection seam the studio
    needs without threading a prompt through every signature. Sequential by design — one A/B at a
    time — and always restored, so the live prompt is never left mutated."""
    old = agents.SPEC_SYSTEM
    agents.SPEC_SYSTEM = text
    try:
        yield
    finally:
        agents.SPEC_SYSTEM = old


@dataclass
class GoalRun:
    goal: str
    accepted: bool
    retries: int


@dataclass
class VariantRun:
    label: str
    runs: list[GoalRun]

    @property
    def accept_rate(self) -> float:
        return sum(r.accepted for r in self.runs) / len(self.runs) if self.runs else 0.0


@dataclass
class TuningVerdict:
    baseline: VariantRun
    candidate: VariantRun

    @property
    def delta(self) -> float:
        """Candidate accept-rate minus baseline — positive means the candidate cleared more gates."""
        return self.candidate.accept_rate - self.baseline.accept_rate

    @property
    def winner(self) -> str:
        if self.delta > 1e-9:
            return "candidate"
        if self.delta < -1e-9:
            return "baseline"
        return "tie"

    @property
    def improved(self) -> bool:
        """True only if the candidate beat the prompt in use on this suite. Trust it only when the
        suite was HELD OUT from the candidate's author (see the module docstring)."""
        return self.winner == "candidate"


def _run_suite(label: str, system: str, goals: list[str], make_provider: ProviderFactory, repeats: int) -> VariantRun:
    runs: list[GoalRun] = []
    with spec_system(system):
        for goal in goals:
            for _ in range(repeats):
                with tempfile.TemporaryDirectory() as d:  # isolated memory: no cross-run learning
                    res = build(goal, make_provider(), MemoryStore(pathlib.Path(d)))
                retries = len([e for e in res.activity if e.actor == "retry"])
                runs.append(GoalRun(goal, res.accepted, retries))
    return VariantRun(label, runs)


def tune_spec_prompt(
    candidate: str,
    *,
    make_provider: ProviderFactory,
    goals: list[str],
    baseline: str | None = None,
    repeats: int = 1,
) -> TuningVerdict:
    """A/B a candidate Spec prompt against the one in use (or an explicit `baseline`) over `goals`.

    Returns who cleared more of the suite's HARD gates. The candidate is adopted only if it wins —
    and only honestly if `goals` were held out from whoever wrote the candidate. Nothing here looks
    at the prompt's wording; the gates decide.
    """
    base_system = baseline if baseline is not None else agents.SPEC_SYSTEM
    base = _run_suite("baseline", base_system, goals, make_provider, repeats)
    cand = _run_suite("candidate", candidate, goals, make_provider, repeats)
    return TuningVerdict(base, cand)
