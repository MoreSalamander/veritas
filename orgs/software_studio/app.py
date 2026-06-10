"""P9 — Assembly: turn a plan into real, composed code.

The Planner's plan becomes modules (each a full P6 build), then those modules must prove
they *coexist* — combine cleanly with no cross-module name clashes and load without error.
That's the new boundary this rung adds, guarded by AssemblyGate.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field

from engine.artifact import Artifact, Determinism, GateResult
from engine.executor import Executor, LocalSubprocessExecutor
from engine.gate import Gate
from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.software_studio.module import ModuleResult, build_module
from orgs.software_studio.plan import PlanGate, PlannerAgent, parse_plan

_EXEC = LocalSubprocessExecutor()


class AssemblyGate(Gate):
    """The composition boundary for an app: the modules must combine cleanly — parse,
    no duplicate top-level function names across modules, and load without error."""

    name = "assembly"
    determinism = Determinism.HARD

    def __init__(self, executor: Executor | None = None, timeout: float = 10.0) -> None:
        self.executor = executor or _EXEC
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        try:
            tree = ast.parse(artifact.payload)
        except SyntaxError as exc:
            return self._result(False, f"package does not parse: {exc}")
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        clashes = sorted({n for n in names if names.count(n) > 1})
        if clashes:
            return self._result(False, f"function name clash across modules: {', '.join(clashes)}")
        result = self.executor.run(artifact.payload, {**os.environ}, self.timeout)
        if not result.ok:
            last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
            return self._result(False, f"package fails to load: {last}")
        return self._result(True, f"{len(names)} functions across modules, no clashes, loads clean")


@dataclass
class AppResult:
    plan_outcome: Outcome
    module_results: list[ModuleResult]
    package_outcome: Outcome | None  # None if plan rejected or a module failed to build
    accepted: bool
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build_app(goal: str, provider: ModelProvider, memory: MemoryStore) -> AppResult:
    run = Run(goal=goal, memory=memory)
    recalled = memory.recall(goal, categories=["failure", "lesson"], limit=3)
    lessons = format_lessons(recalled)
    informed_by = [record.id for record in recalled]

    # PLAN — decompose the app into modules.
    plan_artifact = PlannerAgent(provider).propose(goal, lessons=lessons)
    plan_artifact.provenance.informed_by.extend(informed_by)
    plan_outcome = run.submit(plan_artifact, [PlanGate()])
    if not plan_outcome.accepted:
        return AppResult(plan_outcome, [], None, False, informed_by, run.id, list(run.log))
    plan = parse_plan(plan_artifact.payload)

    # BUILD — each module is a full P6 build of its own.
    module_results: list[ModuleResult] = []
    pieces: list[tuple[str, str]] = []
    for brief in plan.modules:
        result = build_module(brief.goal, provider, memory)
        module_results.append(result)
        if result.accepted and result.code_outcome is not None:
            pieces.append((brief.name, result.code_outcome.artifact.payload))
        else:
            return AppResult(plan_outcome, module_results, None, False, informed_by, run.id, list(run.log))

    # ASSEMBLE — the modules must coexist.
    combined = "\n\n".join(f"# --- module: {name} ---\n{code}" for name, code in pieces)
    package_artifact = Artifact.propose(
        type="package", owner="assembler", payload=combined,
        rationale=f"assembled package for app {plan.app_name}", parent_id=plan_artifact.id,
    )
    package_artifact.provenance.informed_by.extend(informed_by)
    package_outcome = run.submit(package_artifact, [AssemblyGate(), ValidationGate()])
    return AppResult(
        plan_outcome, module_results, package_outcome, package_outcome.accepted,
        informed_by, run.id, list(run.log),
    )
