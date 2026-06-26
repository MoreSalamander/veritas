"""The prompt studio's engine: a candidate prompt wins only by clearing more HARD gates.

Offline and deterministic. A prompt-sensitive fake provider emits a valid spec only when the Spec
system prompt carries a marker, a broken one otherwise — so a function build's accept hinges purely on
whether the prompt was the good one. That lets `tune_spec_prompt` run a real A/B with no model: the
marked prompt beats the unmarked one over the suite, and the verdict is decided by accept-rate, never
by wording.
"""

from __future__ import annotations

import json

from engine.model import ModelProvider
from orgs.software_studio import agents
from orgs.software_studio.tuning import spec_system, tune_spec_prompt

GOOD_SPEC = json.dumps(
    {"function_name": "add", "description": "add", "signature": "def add(a, b)",
     "cases": [{"args": [1, 2], "expected": 3}]}
)
CODE = "def add(a, b):\n    return a + b\n"
DOC = "# add\n\n```python\nassert add(2, 3) == 5\n```\n"

MARKER = "GOLDEN"
GOOD_PROMPT = f"You are a spec writer. {MARKER}. Return the schema."
BAD_PROMPT = GOOD_PROMPT.replace(MARKER, "")  # the only difference — and it's load-bearing


class _SpecMarkerProvider(ModelProvider):
    """Emits a usable spec iff the Spec prompt contains MARKER; otherwise prose the scorer rejects.
    Everything else is fixed-good, so the build's fate is a clean function of the prompt."""

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        if role == "router":
            return "function"
        if role == "spec":
            return GOOD_SPEC if system and MARKER in system else "not a spec, just prose"
        if role == "developer":
            return CODE
        if role == "qa":
            return "[]"
        if role == "doc":
            return DOC
        return ""


def _make_provider() -> ModelProvider:
    return _SpecMarkerProvider()


def test_the_better_prompt_wins_the_ab():
    verdict = tune_spec_prompt(
        BAD_PROMPT, baseline=GOOD_PROMPT, make_provider=_make_provider, goals=["add two numbers", "sum a and b"]
    )
    assert verdict.baseline.accept_rate == 1.0   # marked prompt clears the suite
    assert verdict.candidate.accept_rate == 0.0  # unmarked prompt clears nothing
    assert verdict.winner == "baseline" and not verdict.improved
    assert verdict.delta < 0


def test_a_winning_candidate_is_reported_as_improved():
    # flip it: the marked prompt is now the candidate, the unmarked one the baseline in use
    verdict = tune_spec_prompt(
        GOOD_PROMPT, baseline=BAD_PROMPT, make_provider=_make_provider, goals=["add two numbers"]
    )
    assert verdict.improved and verdict.winner == "candidate" and verdict.delta > 0


def test_the_ab_never_leaves_the_live_prompt_mutated():
    live = agents.SPEC_SYSTEM
    with spec_system("temporarily different"):
        assert agents.SPEC_SYSTEM == "temporarily different"
    assert agents.SPEC_SYSTEM == live  # restored
    tune_spec_prompt(GOOD_PROMPT, baseline=BAD_PROMPT, make_provider=_make_provider, goals=["add"])
    assert agents.SPEC_SYSTEM == live  # the A/B restored it too
