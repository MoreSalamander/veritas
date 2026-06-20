"""Empirical Lab — a claim ships only if a reproducible experiment supports it.

Driven offline: a scripted scientist + experimentalist, a real subprocess executor running real
(hand-written) deterministic Python. A supported, reproducible claim ships; a refuted one, a
non-reproducible one, and a dangerous experiment are each refused by the gate that owns them.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.empirical_lab.experiment import (
    Hypothesis,
    evaluate_prediction,
    parse_hypothesis,
)
from orgs.empirical_lab.gates import (
    HypothesisScorerGate,
    ReproducibilityGate,
    SupportsHypothesisGate,
)
from orgs.empirical_lab.pipeline import build_experiment

HYP = json.dumps({
    "statement": "An ensemble of small models beats a single model on accuracy",
    "metric": "accuracy",
    "prediction": {"type": "compare", "left": "ensemble", "right": "single", "op": ">"},
})
# real, deterministic experiments printing the metric as JSON
SUPPORTS = "import json\nprint(json.dumps({'accuracy': {'ensemble': 0.83, 'single': 0.79}}))"
REFUTES = "import json\nprint(json.dumps({'accuracy': {'ensemble': 0.71, 'single': 0.79}}))"
NONDETERMINISTIC = ("import json, random\n"
                    "print(json.dumps({'accuracy': {'ensemble': random.random(), 'single': 0.5}}))")
DANGEROUS = "import os, json\nos.system('echo hi')\nprint(json.dumps({'accuracy': {'ensemble': 1, 'single': 0}}))"


def _provider(experiment: str) -> ScriptedProvider:
    return ScriptedProvider({"hypothesis": HYP, "experimenter": experiment})


# --- the unit pieces ----------------------------------------------------------------------

def test_hypothesis_scorer_needs_a_checkable_prediction():
    bad = Artifact.propose(type="hypothesis", owner="t",
                           payload=json.dumps({"statement": "x", "metric": "acc"}), rationale="t")
    assert not HypothesisScorerGate().check(bad).passed  # no prediction


def test_evaluate_prediction_reads_the_data():
    h = parse_hypothesis(HYP)
    ok, _ = evaluate_prediction(h, {"accuracy": {"ensemble": 0.9, "single": 0.8}})
    assert ok
    bad, _ = evaluate_prediction(h, {"accuracy": {"ensemble": 0.7, "single": 0.8}})
    assert not bad


# --- the whole chain ----------------------------------------------------------------------

def test_supported_reproducible_claim_ships(tmp_path):
    res = build_experiment("do ensembles beat single models?", _provider(SUPPORTS), MemoryStore(tmp_path))
    assert res.accepted
    assert [o.artifact.type for o in res.outcomes] == ["hypothesis", "experiment", "result"]


def test_refuted_claim_is_rejected(tmp_path):
    # the experiment runs and reproduces, but the data contradicts the hypothesis
    res = build_experiment("do ensembles beat single models?", _provider(REFUTES), MemoryStore(tmp_path))
    assert not res.accepted and len(res.outcomes) == 3
    result_gates = {g.gate_name: g for g in res.outcomes[2].artifact.provenance.gate_results}
    assert result_gates["reproducibility"].passed and not result_gates["supports-hypothesis"].passed


def test_non_reproducible_experiment_is_rejected(tmp_path):
    res = build_experiment("do ensembles beat single models?", _provider(NONDETERMINISTIC), MemoryStore(tmp_path))
    assert not res.accepted
    gates = {g.gate_name: g for g in res.outcomes[2].artifact.provenance.gate_results}
    assert not gates["reproducibility"].passed


def test_dangerous_experiment_is_refused_before_running(tmp_path):
    res = build_experiment("do ensembles beat single models?", _provider(DANGEROUS), MemoryStore(tmp_path))
    assert not res.accepted
    # rejected at the experiment stage (security scan) — never reached the run stage
    assert [o.artifact.type for o in res.outcomes] == ["hypothesis", "experiment"]
    assert not res.outcomes[1].accepted
