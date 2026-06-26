"""The confidence layer governs itself — its safety bound clears the Empirical Lab's own gates.

The reflexive rule (README §4.5): a verification mechanism Veritas ships is trusted only once a
*reproducible* experiment supports it. The knowledge mode's "confident" tier rests on one number —
the confident-wrong rate must stay below the bar that lets it ship labelled. Here that claim, frozen
from the exploratory self-consistency run, is run through the real Empirical Lab stack: the
experiment is security-scanned, executed repeatedly by a real subprocess executor, and judged for
reproducibility and support. No model is involved — the data is pinned, so this is deterministic and
offline. It is the formalization itself, asserted as a test.
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

from bench.experiments.confidence_self_consistency import EXPERIMENT_CODE, HYPOTHESIS


def _hyp_artifact() -> Artifact:
    return Artifact.propose(type="hypothesis", owner="empirical-lab", payload=HYPOTHESIS, rationale="formalization")


def test_the_hypothesis_is_checkable():
    assert HypothesisScorerGate().check(_hyp_artifact()).passed


def test_the_experiment_is_safe_to_run():
    # pure compute over frozen data — no imports beyond json, no I/O, no side effects
    code = Artifact.propose(type="experiment", owner="empirical-lab", payload=EXPERIMENT_CODE, rationale="t")
    assert SecurityScanGate().check(code).passed


def test_the_confidence_bound_ships_reproducible_and_supported():
    hypothesis = parse_hypothesis(HYPOTHESIS)
    manifest = run_experiment(LocalSubprocessExecutor(), EXPERIMENT_CODE, hypothesis.metric, n=3)
    result = Artifact.propose(type="result", owner="empirical-lab", payload=manifest, rationale="t")

    assert ExperimentRunsGate(hypothesis).check(result).passed   # it ran, every time, with the metric
    assert ReproducibilityGate().check(result).passed            # the analysis reproduces exactly
    supports = SupportsHypothesisGate(hypothesis).check(result)
    assert supports.passed                                        # confident-wrong rate < 10%
    # the bound is real, not vacuous: the rate is above zero, so the tier is labelled, never verified
    assert "0.0588" in supports.evidence or "0.058" in supports.evidence
