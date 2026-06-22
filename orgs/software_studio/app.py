"""P9 + P10 — Assembly, then a runnable app.

P9: a plan becomes modules that must coexist as one package (AssemblyGate).
P10: an Integrator wraps the package with a `main` entrypoint, the PM writes an
end-to-end test, and E2EGate proves the whole thing actually runs end to end. That last
gate is what makes it an *app* and not just a pile of functions that happen to coexist.
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
from orgs.software_studio.agents import _strip_code_fences
from orgs.software_studio.module import ModuleResult, build_module, parse_integration
from orgs.software_studio.plan import PlanGate, PlannerAgent, parse_plan

_EXEC = LocalSubprocessExecutor()


def _top_level_functions(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


# --- gates -----------------------------------------------------------------------


class AssemblyGate(Gate):
    """The composition boundary for an app: modules must combine cleanly — parse, no
    duplicate top-level function names across modules, and load without error."""

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
        names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        clashes = sorted({n for n in names if names.count(n) > 1})
        if clashes:
            return self._result(False, f"function name clash across modules: {', '.join(clashes)}")
        result = self.executor.run(artifact.payload, {**os.environ}, self.timeout)
        if not result.ok:
            last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
            return self._result(False, f"package fails to load: {last}")
        return self._result(True, f"{len(names)} functions across modules, no clashes, loads clean")


class EntrypointGate(Gate):
    """The entrypoint must define `main` and load together with the package."""

    name = "entrypoint"
    determinism = Determinism.HARD

    def __init__(self, package_code: str, executor: Executor | None = None, timeout: float = 10.0) -> None:
        self.package_code = package_code
        self.executor = executor or _EXEC
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        try:
            tree = ast.parse(artifact.payload)
        except SyntaxError as exc:
            return self._result(False, f"entrypoint syntax error: {exc}")
        if not any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "main"
            for n in ast.walk(tree)
        ):
            return self._result(False, "no main() entrypoint defined")
        result = self.executor.run(f"{self.package_code}\n{artifact.payload}", {**os.environ}, self.timeout)
        if not result.ok:
            last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
            return self._result(False, f"entrypoint fails to load with the package: {last}")
        return self._result(True, "main() defined; loads with the package")


class E2ESpecGate(Gate):
    name = "e2e-spec"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            tests = parse_integration(artifact.payload)
        except Exception as exc:  # IntegrationParseError or malformed
            return self._result(False, f"e2e spec not usable: {exc}")
        if not any("main" in t for t in tests):
            return self._result(False, "no e2e test drives main()")
        return self._result(True, f"{len(tests)} end-to-end test(s)")


class E2EGate(Gate):
    """Run the e2e tests against the whole app (package + entrypoint). Gates the ENTRYPOINT
    artifact, so on a retry the re-written main() is re-checked against the same tests."""

    name = "e2e"
    determinism = Determinism.HARD

    def __init__(
        self, package_code: str, tests: list[str], executor: Executor | None = None, timeout: float = 10.0
    ) -> None:
        self.package_code = package_code
        self.tests = tests
        self.executor = executor or _EXEC
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        app_code = f"{self.package_code}\n{artifact.payload}"
        for index, test in enumerate(self.tests):
            result = self.executor.run(f"import math\n{app_code}\n{test}\n", {**os.environ}, self.timeout)
            if not result.ok:
                last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
                return self._result(False, f"e2e test {index} failed: `{test.strip()}` -> {last}")
        return self._result(True, f"{len(self.tests)}/{len(self.tests)} e2e tests pass — the app runs end to end")


# --- the Integrator role + e2e author -------------------------------------------

INTEGRATOR_SYSTEM = (
    "You are an integrator. Given an app goal, the available functions, and the end-to-end tests "
    "the app MUST pass, write a single entrypoint `def main(...)` that composes the functions so "
    "EVERY test passes. Call main(...) with the EXACT signature the tests use. The functions are "
    "ALREADY DEFINED — call them by name, do not redefine. Output ONLY the Python defining main."
)
E2E_SYSTEM = (
    "You are a PM defining end-to-end acceptance for an app. You DESIGN a single entrypoint "
    "`main(...)` and write the tests that exercise it. Respond with ONLY a JSON array of Python "
    "assertion strings that CALL main(...), using ONE consistent simple signature across all "
    "tests. PREFER checks that don't require computing exact numbers (round-trips, invariants, "
    "fixed points); for floats use math.isclose(...), never ==. `math` is available. No prose, no fences."
)


class IntegratorAgent:
    role = "integrator"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(
        self, goal: str, function_names: list[str], tests: list[str], parent_id: str,
        lessons: str | None = None, feedback: str | None = None,
    ) -> Artifact:
        prompt = (
            f"App goal: {goal}\nAvailable functions: {', '.join(function_names)}\n"
            f"End-to-end tests main() must pass:\n" + "\n".join(tests)
        )
        if feedback:
            prompt = f"Your previous main() was REJECTED: {feedback}\nFix it.\n\n{prompt}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=INTEGRATOR_SYSTEM)
        return Artifact.propose(
            type="entrypoint", owner="integrator-agent", payload=_strip_code_fences(raw),
            rationale=f"entrypoint for app: {goal}", parent_id=parent_id,
        )


# --- the pipeline ----------------------------------------------------------------


@dataclass
class AppResult:
    plan_outcome: Outcome
    module_results: list[ModuleResult]
    package_outcome: Outcome | None
    entrypoint_outcome: Outcome | None
    e2e_outcome: Outcome | None
    accepted: bool
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build_app(goal: str, provider: ModelProvider, memory: MemoryStore) -> AppResult:
    run = Run(goal=goal, memory=memory, max_attempts=provider.retry_budget())
    recalled = memory.recall(goal, categories=["failure", "lesson", "decision"], limit=3)
    lessons = format_lessons(recalled)
    informed_by = [record.id for record in recalled]

    def result(plan_o, mods, pkg_o, entry_o, e2e_o, accepted) -> AppResult:  # type: ignore[no-untyped-def]
        return AppResult(plan_o, mods, pkg_o, entry_o, e2e_o, accepted, informed_by, run.id, list(run.log))

    # PLAN
    plan_artifact = PlannerAgent(provider).propose(goal, lessons=lessons)
    plan_artifact.provenance.informed_by.extend(informed_by)
    plan_outcome = run.submit(plan_artifact, [PlanGate()])
    if not plan_outcome.accepted:
        return result(plan_outcome, [], None, None, None, False)
    plan = parse_plan(plan_artifact.payload)

    # BUILD each module (a full P6 build of its own)
    module_results: list[ModuleResult] = []
    pieces: list[tuple[str, str]] = []
    for brief in plan.modules:
        mr = build_module(brief.goal, provider, memory)
        module_results.append(mr)
        if mr.accepted and mr.code_outcome is not None:
            pieces.append((brief.name, mr.code_outcome.artifact.payload))
        else:
            return result(plan_outcome, module_results, None, None, None, False)

    # ASSEMBLE — the modules must coexist
    combined = "\n\n".join(f"# --- module: {name} ---\n{code}" for name, code in pieces)
    package_artifact = Artifact.propose(
        type="package", owner="assembler", payload=combined,
        rationale=f"assembled package for app {plan.app_name}", parent_id=plan_artifact.id,
    )
    package_artifact.provenance.informed_by.extend(informed_by)
    package_outcome = run.submit(package_artifact, [AssemblyGate(), ValidationGate()])
    if not package_outcome.accepted:
        return result(plan_outcome, module_results, package_outcome, None, None, False)

    package_code = package_artifact.payload
    function_names = _top_level_functions(package_code)

    # E2E SPEC — the PM designs main()'s contract by writing the tests it must pass.
    e2e_raw = provider.propose(
        role="pm",
        prompt=f"App goal: {goal}\nThe package exposes these functions: {', '.join(function_names)}",
        system=E2E_SYSTEM,
    )
    e2e_artifact = Artifact.propose(
        type="e2e-spec", owner="pm-agent", payload=e2e_raw,
        rationale=f"end-to-end acceptance for app {plan.app_name}", parent_id=package_artifact.id,
    )
    e2e_artifact.provenance.informed_by.extend(informed_by)
    e2e_outcome = run.submit(e2e_artifact, [E2ESpecGate()])
    if not e2e_outcome.accepted:
        return result(plan_outcome, module_results, package_outcome, None, e2e_outcome, False)
    tests = parse_integration(e2e_artifact.payload)

    # ENTRYPOINT — implement main() to satisfy the e2e tests; retry against the e2e gate so
    # a main that doesn't match the tests' interface or behavior fixes itself.
    def propose_entry(feedback: str | None) -> Artifact:
        art = IntegratorAgent(provider).propose(
            goal, function_names, tests, parent_id=package_artifact.id, lessons=lessons, feedback=feedback
        )
        art.provenance.informed_by.extend(informed_by)
        return art

    entry_outcome = run.attempt(
        propose_entry,
        [EntrypointGate(package_code), E2EGate(package_code, tests), ValidationGate()],
    )
    return result(
        plan_outcome, module_results, package_outcome, entry_outcome, e2e_outcome, entry_outcome.accepted
    )
