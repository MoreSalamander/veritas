"""The confidence layer's safety bound, formalized as a reproducible Empirical Lab experiment.

`bench/selfconsistency.py` was *exploration* — a live gemma4:12b run (temp 0.8) over 23
ground-truthed questions that decided how the knowledge mode should flag unreliable answers. A live
sampling run is, by construction, **not reproducible**: re-run it and the numbers drift. That makes
it unfit to *govern* anything — and the reflexive rule (see README §4.5) is that no verification
mechanism Veritas ships may be trusted on an irreproducible measurement.

So this is the promotion. The exploratory run is frozen into a pinned transcript of per-question
measurements (the recorded `selfconsistency_20260622-182254.md`, 8 samples/question), and the
load-bearing number — the **confident-wrong rate** — is recomputed *deterministically* from that
frozen data. Now it reproduces exactly, so it can clear the Empirical Lab's ReproducibilityGate and
be checked against a real prediction by SupportsHypothesisGate. The reproducibility is of the
*analysis*, not of the model sampling; that boundary is the honest part — the sampling stays
exploratory, the bound that governs the "confident" tier is reproducible.

The claim under test: among answers the model asserts *confidently* (self-consistency ≥ 80% AND no
elicited hedge), the wrong-answer rate is **below 10%** — low enough to ship a "confident" tier
*labelled*, yet (being above 0) never low enough to call it verified. That is precisely the number
that bounds what the tier may claim.

Two exports drive the formalization:
  * ``HYPOTHESIS`` — the checkable claim (a threshold prediction the Empirical Lab can evaluate).
  * ``EXPERIMENT_CODE`` — a self-contained, deterministic, side-effect-free script (it embeds the
    frozen data) that prints the metric as JSON. It is what the org security-scans and then runs
    repeatedly. Running this module directly prints the same JSON, so the experiment is inspectable.
"""

from __future__ import annotations

import json

# The pinned claim. metric "confidence" carries the conditions the prediction reads.
HYPOTHESIS = json.dumps({
    "statement": (
        "Among answers gemma4:12b asserts confidently (self-consistency >= 80% AND no elicited "
        "hedge), the wrong-answer rate is below 10% — low enough to ship a 'confident' tier "
        "labelled, but (being > 0) never low enough to call it verified."
    ),
    "metric": "confidence",
    "prediction": {"type": "threshold", "condition": "confident_wrong_rate", "op": "<", "value": 0.10},
})

# The experiment: pure compute over a frozen transcript, so two runs are byte-identical.
# Each row is (category, agreement, hedge_rate, verdict) from the recorded 8-sample run; verdict is
# "yes"/"no" for a judged factual answer, "unknowable" (no ground truth), or "trap" (false premise,
# excluded from the rate exactly as the original instrument did).
EXPERIMENT_CODE = r'''
import json

ROWS = [
    ("well-known", 1.00, 0.00, "yes"), ("well-known", 1.00, 0.00, "yes"),
    ("well-known", 1.00, 0.00, "yes"), ("well-known", 1.00, 0.00, "yes"),
    ("well-known", 1.00, 0.00, "yes"),
    ("established", 1.00, 0.00, "yes"), ("established", 1.00, 0.00, "yes"),
    ("established", 1.00, 0.00, "yes"), ("established", 1.00, 0.00, "yes"),
    ("established", 1.00, 0.00, "yes"),
    ("obscure", 1.00, 0.00, "yes"),          # Ice Spice — correct
    ("obscure", 1.00, 0.00, "yes"),          # Hollow Knight — correct
    ("obscure", 0.75, 0.00, "no"),           # Wet Leg — wrong, caught by LOW agreement
    ("obscure", 0.88, 0.00, "no"),           # black midi — wrong, NOT caught: the blind spot
    ("obscure", 1.00, 1.00, "unknowable"),   # Latvian attendance — hedged
    ("obscure", 1.00, 1.00, "unknowable"),   # Geese bassist — hedged
    ("recent", 1.00, 0.00, "yes"),           # US 2024 election
    ("recent", 1.00, 0.00, "yes"),           # Euro 2024
    ("recent", 1.00, 0.00, "yes"),           # 2024 World Series
    ("recent", 1.00, 1.00, "no"),            # Super Bowl LIX — wrong but HEDGED (flagged)
    ("recent", 1.00, 0.00, "yes"),           # Best Picture 2024
    ("trap", 0.88, 0.00, "trap"),            # Einstein — false-premise trap (excluded)
    ("trap", 1.00, 0.00, "trap"),            # da Vinci — false-premise trap (excluded)
]

HIGH = 0.80  # self-consistency at/above this is "confident"

# only factual answers with a ground truth are judged; unknowables and traps are not assertions
# of a checkable fact, so they cannot be "confidently wrong" in the sense the tier cares about.
judged = [r for r in ROWS if r[3] in ("yes", "no")]
# a hedged answer (>=50% of samples said "I don't know") is not a confident assertion at all.
confident = [r for r in judged if r[1] >= HIGH and r[2] < 0.50]
confident_wrong = [r for r in confident if r[3] == "no"]
rate = len(confident_wrong) / len(confident)

print(json.dumps({"confidence": {
    "confident_wrong_rate": round(rate, 6),
    "confident_n": len(confident),
    "confident_wrong_n": len(confident_wrong),
    "judged_n": len(judged),
}}))
'''


if __name__ == "__main__":
    exec(compile(EXPERIMENT_CODE, "<experiment>", "exec"))
