"""The Empirical Lab run: a question becomes a hypothesis, an experiment, and a verified result.

The chain is strict and safe: the hypothesis must be checkable, the experiment code is
security-scanned BEFORE it is ever executed, and only then is it run — repeatedly — and the result
judged for reproducibility and support. A claim the data refutes, or an experiment that won't
reproduce, is rejected; the refutation lands in failure memory (knowledge either way).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.artifact import Artifact
from engine.executor import Executor, LocalSubprocessExecutor
from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.empirical_lab.agents import (
    ExperimentRunnerAgent,
    ExperimenterAgent,
    HypothesisAgent,
)
from orgs.empirical_lab.experiment import parse_hypothesis
from orgs.empirical_lab.gates import (
    ExperimentRunsGate,
    HypothesisScorerGate,
    ReproducibilityGate,
    SupportsHypothesisGate,
)
from orgs.software_studio.gates import SecurityScanGate


@dataclass
class ExperimentBuildResult:
    outcomes: list[Outcome]  # hypothesis, experiment, result — fewer if it stopped early
    accepted: bool
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build_experiment(
    question: str, provider: ModelProvider, memory: MemoryStore, executor: Executor | None = None,
) -> ExperimentBuildResult:
    runner_executor = executor or LocalSubprocessExecutor()
    run = Run(goal=question, memory=memory)
    recalled = memory.recall(question, categories=["failure", "lesson", "decision"], limit=3)
    lessons = format_lessons(recalled) or ""
    informed_by = [r.id for r in recalled]
    outcomes: list[Outcome] = []

    def _stamp(art: Artifact) -> Artifact:
        art.provenance.informed_by.extend(informed_by)
        return art

    # Stage 1 — the hypothesis (must carry a checkable prediction)
    hyp_out = run.attempt(
        lambda fb: _stamp(HypothesisAgent(provider).propose(question, lessons, fb)),
        [HypothesisScorerGate(), ValidationGate()],
    )
    outcomes.append(hyp_out)
    if not hyp_out.accepted:
        return ExperimentBuildResult(outcomes, False, informed_by, run.id, list(run.log))
    hypothesis = parse_hypothesis(hyp_out.artifact.payload)

    # Stage 2 — the experiment code, SECURITY-SCANNED before it is ever run
    exp_out = run.attempt(
        lambda fb: _stamp(ExperimenterAgent(provider).propose(hypothesis, lessons, fb)),
        [SecurityScanGate(), ValidationGate()],
    )
    outcomes.append(exp_out)
    if not exp_out.accepted:
        return ExperimentBuildResult(outcomes, False, informed_by, run.id, list(run.log))

    # Stage 3 — run it (now safe), then judge reproducibility + support
    result_art = _stamp(
        ExperimentRunnerAgent(runner_executor).propose(exp_out.artifact.payload, hypothesis))
    result_out = run.submit(
        result_art,
        [ExperimentRunsGate(hypothesis), ReproducibilityGate(),
         SupportsHypothesisGate(hypothesis), ValidationGate()],
    )
    outcomes.append(result_out)
    return ExperimentBuildResult(outcomes, result_out.accepted, informed_by, run.id, list(run.log))
