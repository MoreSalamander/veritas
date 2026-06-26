"""A proposer-prompt change, gated the org's own way — formalized as a reproducible experiment.

`bench/promptbench.py` was the *exploration*: it established (qwen-9b, temp 0) that a prompt change
moves the verified bar, and that the move reproduces. This is the *promotion* — the same move every
other mechanism makes under the reflexive rule (README §4.5): the load-bearing claim is frozen into a
deterministic, re-runnable experiment and put through the Empirical Lab's own gates.

The claim under test is the one the prompt studio rests on: **a proposer prompt's quality is visible
in accept-rate over a goal suite, and the verdict reproduces** — so a prompt change can be *gated*
(trusted only when a reproducible experiment supports it) instead of *eyeballed* (the mistake the
standalone "polish" tools make; promptbench showed a human-cosmetic reword was a 67-point regression).

Concretely: over the goal suite {reverse, clamp, double}, the live `baseline` SPEC_SYSTEM beats a
`vague` (degraded) variant on accept-rate — robustly, across the suite (the degradation hit every
goal, so the verdict doesn't hinge on any one of them). The frozen per-(variant, goal) accept-rates
are the temp-0, 3×-agreeing results from that run; recomputing the suite means is deterministic, so
two runs are byte-identical and the ReproducibilityGate passes. As with the confidence bound, the
reproducibility is of the *analysis*, not of the model — that boundary is the honest part.

Scope note: this experiment proves the *detection mechanism* on a frozen suite (a degraded prompt is
reproducibly worse). When the studio later tunes a prompt to *improve* it, its experiments must score
on a **held-out** goal suite — accept-rate gains on the tuning goals could be overfitting (teaching to
the test, the prompt analogue of judge collusion); only a gain that reproduces on unseen goals counts.

Exports `HYPOTHESIS` (the checkable claim) and `EXPERIMENT_CODE` (the self-contained, deterministic,
side-effect-free script that prints the metric as JSON). Running this module prints that JSON.
"""

from __future__ import annotations

import json

# The pinned claim: over the suite, baseline accept-rate exceeds the degraded variant's.
HYPOTHESIS = json.dumps({
    "statement": (
        "A proposer prompt's quality is visible and reproducible in accept-rate over a goal suite: "
        "the live SPEC_SYSTEM (baseline) clears more of the suite's HARD gates than a degraded "
        "(vague) variant — so a prompt change can be gated empirically, not eyeballed."
    ),
    "metric": "accept_rate",
    "prediction": {"type": "compare", "left": "baseline", "right": "vague", "op": ">"},
})

# The experiment: pure compute over a frozen transcript of temp-0, 3x-agreeing accept-rates, so two
# runs are byte-identical. Each entry is variant -> {goal: accept_rate}; the metric is the suite mean.
EXPERIMENT_CODE = r'''
import json

# frozen accept-rates from bench/promptbench.py (qwen-9b, temp 0, 3x — every cell agreed 0/3 or 3/3)
FROZEN = {
    "baseline": {"reverse": 1.0, "clamp": 1.0, "double": 1.0},
    "cosmetic": {"reverse": 0.0, "clamp": 0.0, "double": 1.0},   # meaning-preserving reword, yet worse
    "vague":    {"reverse": 0.0, "clamp": 0.0, "double": 0.0},   # realistic degradation
}

# the verdict is over the SUITE, never one goal — a single goal can mislead (cosmetic's damage was
# goal-specific; vague's was not). Accept-rate = mean over the suite.
suite = sorted({g for v in FROZEN.values() for g in v})
accept_rate = {v: round(sum(FROZEN[v][g] for g in suite) / len(suite), 6) for v in FROZEN}

print(json.dumps({"accept_rate": accept_rate}))
'''


if __name__ == "__main__":
    exec(compile(EXPERIMENT_CODE, "<experiment>", "exec"))
