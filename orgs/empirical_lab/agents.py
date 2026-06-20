"""The Empirical Lab's cast. The scientist proposes a falsifiable hypothesis; the experimentalist
writes a deterministic experiment that tests it; the runner executes it (a tool, not a model). Critic
and Validation are GATES, not agents — judgment of the result is the deterministic gate layer."""

from __future__ import annotations

from engine.artifact import Artifact
from engine.executor import Executor
from engine.model import ModelProvider
from orgs.empirical_lab.experiment import Hypothesis, run_experiment
from orgs.software_studio.agents import _strip_code_fences

HYPOTHESIS_SYSTEM = (
    "You are a research scientist. Given a research question, state a single FALSIFIABLE hypothesis "
    "with a machine-checkable prediction. Respond with ONLY JSON: {\"statement\": \"...\", "
    "\"metric\": \"<name>\", \"prediction\": {\"type\": \"compare\", \"left\": \"<conditionA>\", "
    "\"right\": \"<conditionB>\", \"op\": \">\"}} — or for an absolute bar use {\"type\": "
    "\"threshold\", \"condition\": \"<cond>\", \"op\": \">=\", \"value\": <number>}. The metric and "
    "condition names are exactly what the experiment will measure. Output ONLY the JSON."
)

EXPERIMENT_SYSTEM = (
    "You are an experimentalist. Write a SELF-CONTAINED, DETERMINISTIC Python experiment that tests "
    "the hypothesis and prints its result as JSON to stdout. HARD RULES: (1) print ONLY one JSON "
    "object mapping the metric to each condition's value, e.g. "
    "print(json.dumps({\"<metric>\": {\"<condA>\": 0.83, \"<condB>\": 0.79}})). (2) It MUST be "
    "deterministic — seed every source of randomness (random.seed(0), etc.) so a second run gives "
    "the IDENTICAL numbers. (3) No file, network, or system access; standard library only. Output "
    "ONLY the Python code."
)


def _with_feedback(prompt: str, feedback: str | None) -> str:
    if feedback:
        return f"Your previous attempt was REJECTED: {feedback}\nFix exactly that.\n\n{prompt}"
    return prompt


class HypothesisAgent:
    role = "hypothesis"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, question: str, lessons: str = "", feedback: str | None = None) -> Artifact:
        body = f"{lessons}Research question: {question}" if lessons else f"Research question: {question}"
        raw = self.provider.propose(role=self.role, prompt=_with_feedback(body, feedback),
                                    system=HYPOTHESIS_SYSTEM)
        return Artifact.propose(type="hypothesis", owner="hypothesis-agent",
                                payload=_strip_code_fences(raw), rationale=f"hypothesis for: {question}")


class ExperimenterAgent:
    role = "experimenter"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, hypothesis: Hypothesis, lessons: str = "", feedback: str | None = None) -> Artifact:
        conds = (f"{hypothesis.prediction.left}, {hypothesis.prediction.right}"
                 if hypothesis.prediction.kind == "compare" else hypothesis.prediction.condition)
        body = (f"{lessons}Hypothesis: {hypothesis.statement}\nMetric to measure: {hypothesis.metric}"
                f"\nConditions to report: {conds}")
        raw = self.provider.propose(role=self.role, prompt=_with_feedback(body, feedback),
                                    system=EXPERIMENT_SYSTEM)
        return Artifact.propose(type="experiment", owner="experimenter-agent",
                                payload=_strip_code_fences(raw),
                                rationale=f"experiment for: {hypothesis.metric}")


class ExperimentRunnerAgent:
    """Executes the (already security-scanned) experiment N times → the run manifest artifact."""

    role = "experiment-runner"

    def __init__(self, executor: Executor, runs: int = 2, timeout: float = 30.0) -> None:
        self.executor = executor
        self.runs = runs
        self.timeout = timeout

    def propose(self, code: str, hypothesis: Hypothesis) -> Artifact:
        manifest = run_experiment(self.executor, code, hypothesis.metric, self.runs, self.timeout)
        return Artifact.propose(type="result", owner="experiment-runner", payload=manifest,
                                rationale=f"ran the experiment {self.runs}x")
