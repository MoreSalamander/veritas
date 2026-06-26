"""Prompt-tuning governs itself — a proposer-prompt verdict clears the Empirical Lab's own gates.

The bootstrap claim (the strange loop): Veritas can improve its own proposer prompts, and trust the
improvement *the org's own way* — by a reproducible accept-rate experiment, not by eyeballing the
prompt. Here the frozen verdict from the prompt-bench run (baseline beats a degraded variant over a
goal suite) is run through the real Empirical Lab stack: security-scanned, executed repeatedly by a
real subprocess executor, judged for reproducibility and support. No model is involved — the data is
pinned, so this is deterministic and offline. It is the formalization, asserted as a test.
"""

from __future__ import annotations

from engine.artifact import Artifact
from engine.executor import LocalSubprocessExecutor
from orgs.empirical_lab.experiment import parse_hypothesis, run_experiment
from orgs.empirical_lab.gates import (
    ExperimentRunsGate,
    HypothesisScorerGate,
    ReproducibilityGate,
    SupportsHypothesisGate,
)
from orgs.software_studio.gates import SecurityScanGate

from bench.experiments.prompt_accept_rate import EXPERIMENT_CODE, HYPOTHESIS


def _hyp_artifact() -> Artifact:
    return Artifact.propose(type="hypothesis", owner="empirical-lab", payload=HYPOTHESIS, rationale="formalization")


def test_the_prompt_hypothesis_is_checkable():
    assert HypothesisScorerGate().check(_hyp_artifact()).passed


def test_the_experiment_is_safe_to_run():
    code = Artifact.propose(type="experiment", owner="empirical-lab", payload=EXPERIMENT_CODE, rationale="t")
    assert SecurityScanGate().check(code).passed


def test_the_prompt_verdict_ships_reproducible_and_supported():
    hypothesis = parse_hypothesis(HYPOTHESIS)
    manifest = run_experiment(LocalSubprocessExecutor(), EXPERIMENT_CODE, hypothesis.metric, n=3)
    result = Artifact.propose(type="result", owner="empirical-lab", payload=manifest, rationale="t")

    assert ExperimentRunsGate(hypothesis).check(result).passed   # it ran every time, reporting accept_rate
    assert ReproducibilityGate().check(result).passed            # the suite verdict reproduces exactly
    supports = SupportsHypothesisGate(hypothesis).check(result)
    assert supports.passed                                        # baseline > vague over the suite
    assert "baseline=1" in supports.evidence and "vague=0" in supports.evidence
