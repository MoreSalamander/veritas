"""The Empirical Lab's roster for the Hub's Org view. Cast authored here; gate determinism read
straight off the classes so the page can't drift."""

from __future__ import annotations

from typing import Any

from engine.gate import Gate
from engine.validation import ValidationGate
from orgs.empirical_lab.gates import (
    ExperimentRunsGate,
    HypothesisScorerGate,
    ReproducibilityGate,
    SupportsHypothesisGate,
)
from orgs.software_studio.gates import SecurityScanGate

_CAST: list[tuple[str, str, str]] = [
    ("Scientist", "hypothesis", "Turns a research question into one falsifiable hypothesis with a machine-checkable prediction (a comparison or a threshold on a named metric)."),
    ("Experimentalist", "experimenter", "Writes a self-contained, deterministic experiment that measures the metric and prints its result; re-writes on rejection (e.g. \"dangerous call: os.system()\")."),
    ("Experiment Runner", "experiment-runner", "Executes the security-scanned experiment repeatedly and records each result (a tool call — the gates rule on the data, not the model's claim)."),
]

_GATES: list[tuple[type[Gate], str, str]] = [
    (HypothesisScorerGate, "hypothesis", "the hypothesis carries a prediction a result can confirm or refute — otherwise there's nothing to test"),
    (SecurityScanGate, "experiment", "the experiment code is free of dangerous calls (scanned BEFORE it is ever run)"),
    (ExperimentRunsGate, "result", "the experiment actually ran, every time, and produced the metric"),
    (ReproducibilityGate, "result", "independent runs give the same answer — a result that won't reproduce can't support a claim"),
    (SupportsHypothesisGate, "result", "the measured data satisfies the prediction — the data decides, not the model; a refuted claim is rejected"),
    (ValidationGate, "result", "final authority: every hard gate passed, provenance complete"),
]


def roster() -> dict[str, Any]:
    return {
        "cast": [{"name": n, "role": r, "produces": p} for n, r, p in _CAST],
        "gates": [
            {"name": g.name, "determinism": g.determinism.value, "scope": scope, "about": about}
            for g, scope, about in _GATES
        ],
        "principle": "A hypothesis is verified by REPRODUCIBILITY, not by argument. The experiment "
        "is run, it must reproduce, and the measured data — not the model's assertion — must satisfy "
        "the prediction. A claim the experiment refutes is rejected; the refutation is remembered.",
    }
