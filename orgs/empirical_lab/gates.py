"""The Empirical Lab's gates — the reproducibility verification model made executable.

The hypothesis must be a checkable claim; the experiment code is security-scanned (reusing the
software org's scan) before it is ever run; then the run manifest is judged: the experiment RAN and
produced the metric, it REPRODUCES across runs, and the data SUPPORTS the prediction. A claim the
experiment refutes is rejected — the result is a fact, not the model's say-so.
"""

from __future__ import annotations

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from orgs.empirical_lab.experiment import (
    ExperimentParseError,
    Hypothesis,
    evaluate_prediction,
    hypothesis_completeness,
    parse_hypothesis,
    parse_manifest,
    results_match,
)


class HypothesisScorerGate(Gate):
    """HARD: the hypothesis parses and carries a checkable prediction — else there's nothing an
    experiment could confirm or refute."""

    name = "hypothesis-scorer"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            h = parse_hypothesis(artifact.payload)
        except ExperimentParseError as exc:
            return self._result(False, f"hypothesis not usable: {exc}")
        complete, missing = hypothesis_completeness(h)
        if not complete:
            return self._result(False, f"hypothesis not checkable — missing: {', '.join(missing)}")
        return self._result(True, f"checkable: predicts {h.prediction.kind} on '{h.metric}'")


class ExperimentRunsGate(Gate):
    """HARD: the experiment actually ran (every repetition) and produced the hypothesis's metric."""

    name = "experiment-runs"
    determinism = Determinism.HARD

    def __init__(self, hypothesis: Hypothesis, min_runs: int = 2) -> None:
        self.metric = hypothesis.metric
        self.min_runs = min_runs

    def check(self, artifact: Artifact) -> GateResult:
        try:
            m = parse_manifest(artifact.payload)
        except ExperimentParseError as exc:
            return self._result(False, f"run manifest not usable: {exc}")
        if m.error:
            return self._result(False, f"experiment failed to run: {m.error}")
        if len(m.runs) < self.min_runs:
            return self._result(False, f"only {len(m.runs)} run(s), need {self.min_runs}")
        for i, r in enumerate(m.runs):
            if self.metric not in r:
                return self._result(False, f"run {i} produced no '{self.metric}' measurement")
        return self._result(True, f"ran {len(m.runs)}x, each reporting '{self.metric}'")


class ReproducibilityGate(Gate):
    """HARD — the distinctive one: independent runs give the same answer. A result that won't
    reproduce can't support a claim, no matter what it says once."""

    name = "reproducibility"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            m = parse_manifest(artifact.payload)
        except ExperimentParseError as exc:
            return self._result(False, f"run manifest not usable: {exc}")
        if len(m.runs) < 2:
            return self._result(False, "need at least two runs to check reproducibility")
        ok, evidence = results_match(m.runs[0], m.runs[1])
        return self._result(ok, evidence)


class SupportsHypothesisGate(Gate):
    """HARD: the measured result satisfies the hypothesis's prediction. The data decides; a claim the
    experiment refutes is rejected (and filed as a refutation, which is itself knowledge)."""

    name = "supports-hypothesis"
    determinism = Determinism.HARD

    def __init__(self, hypothesis: Hypothesis) -> None:
        self.hypothesis = hypothesis

    def check(self, artifact: Artifact) -> GateResult:
        try:
            m = parse_manifest(artifact.payload)
        except ExperimentParseError as exc:
            return self._result(False, f"run manifest not usable: {exc}")
        if not m.runs:
            return self._result(False, "no result to test the hypothesis against")
        ok, evidence = evaluate_prediction(self.hypothesis, m.runs[0])
        return self._result(ok, evidence)
