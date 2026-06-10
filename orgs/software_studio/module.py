"""P6 — the software org builds a small MODULE: several functions that work together.

Two roles earn their seats here, because the deliverable is now a *composition*:
- Architect -> the CONTRACT (which functions exist, their signatures, per-function cases).
- PM        -> the INTEGRATION test (criteria that exercise >= 2 functions together).

And a new failure mode appears that could not exist for a single function: each function
passes its own cases, yet they fail when composed. So a new boundary gets its own gate —
IntegrationGate runs the PM's test against the assembled module. New boundary, new gate.
"""

from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass, field
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.executor import Executor, LocalSubprocessExecutor
from engine.gate import Gate
from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.software_studio.agents import _strip_code_fences
from orgs.software_studio.gates import SecurityScanGate
from orgs.software_studio.spec import Case

_EXEC = LocalSubprocessExecutor()


# --- the contract (Architect's artifact) and the integration spec (PM's artifact) ---


class ContractParseError(ValueError):
    """The proposed module contract is not usable. ContractGate rejects on this."""


class IntegrationParseError(ValueError):
    """The proposed integration spec is not usable. IntegrationSpecGate rejects on this."""


@dataclass
class FunctionSpec:
    name: str
    signature: str
    cases: list[Case]


@dataclass
class ModuleContract:
    module_name: str
    functions: list[FunctionSpec]


def _extract_object(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ContractParseError("no JSON object found")
    return text[start : end + 1]


def parse_contract(payload: str) -> ModuleContract:
    try:
        obj: Any = json.loads(_extract_object(payload))
    except (ValueError, TypeError) as exc:
        raise ContractParseError(f"contract is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ContractParseError("contract must be a JSON object")

    name = obj.get("module_name")
    if not isinstance(name, str) or not name.strip():
        raise ContractParseError("missing module_name")

    raw_functions = obj.get("functions")
    if not isinstance(raw_functions, list) or len(raw_functions) < 2:
        raise ContractParseError("a module needs at least 2 functions")

    functions: list[FunctionSpec] = []
    seen: set[str] = set()
    for entry in raw_functions:
        if not isinstance(entry, dict):
            raise ContractParseError("each function must be an object")
        fn = entry.get("function_name")
        if not isinstance(fn, str) or not fn.isidentifier():
            raise ContractParseError(f"function_name missing or invalid: {fn!r}")
        if fn in seen:
            raise ContractParseError(f"duplicate function: {fn}")
        seen.add(fn)
        raw_cases = entry.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ContractParseError(f"{fn}: needs at least one case")
        cases: list[Case] = []
        for case in raw_cases:
            if (
                not isinstance(case, dict)
                or not isinstance(case.get("args"), list)
                or "expected" not in case
            ):
                raise ContractParseError(f"{fn}: malformed case")
            cases.append(Case(args=case["args"], expected=case["expected"]))
        functions.append(FunctionSpec(name=fn, signature=str(entry.get("signature", "")), cases=cases))

    return ModuleContract(module_name=name, functions=functions)


def parse_integration(payload: str) -> list[str]:
    start, end = payload.find("["), payload.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise IntegrationParseError("no JSON array of integration tests found")
    try:
        arr: Any = json.loads(payload[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise IntegrationParseError(f"not valid JSON: {exc}") from exc
    tests = [t for t in arr if isinstance(t, str) and t.strip()]
    if not tests:
        raise IntegrationParseError("no usable integration tests")
    return tests


# --- the new roles ---------------------------------------------------------------

ARCHITECT_SYSTEM = (
    "You are a software architect. Given a goal, design a small module as ONLY a JSON "
    "object — no prose, no fences. Schema: {\"module_name\": <identifier>, \"functions\": "
    "[{\"function_name\": <identifier>, \"signature\": <string>, \"description\": <string>, "
    "\"cases\": [{\"args\": [...], \"expected\": <value>}]}]}. Provide AT LEAST 2 related "
    "functions, each with at least one concrete case."
)
PM_SYSTEM = (
    "You are a product manager defining acceptance for a module. Given its functions, "
    "respond with ONLY a JSON array of Python assertion strings — no prose, no fences. Each "
    "test must CALL AT LEAST TWO of the functions together. PREFER checks that DO NOT require "
    "you to compute exact numbers — round-trips that should return the input "
    "(e.g. assert math.isclose(f(g(x)), x)), invariants, and known fixed points. For any float "
    "comparison use math.isclose(...), never ==. `math` is available. The functions are "
    "already defined; just call them by name."
)
MODULE_DEV_SYSTEM = (
    "You are a developer. Given a module contract (JSON), respond with ONLY Python source "
    "defining EVERY function named in the contract, each satisfying its cases. No prose, no "
    "fences, no tests."
)


def _contract_to_json(contract: ModuleContract) -> str:
    return json.dumps(
        {
            "module_name": contract.module_name,
            "functions": [
                {
                    "function_name": f.name,
                    "signature": f.signature,
                    "cases": [{"args": c.args, "expected": c.expected} for c in f.cases],
                }
                for f in contract.functions
            ],
        }
    )


class ArchitectAgent:
    role = "architect"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, goal: str, lessons: str | None = None) -> Artifact:
        prompt = f"Goal: {goal}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=ARCHITECT_SYSTEM)
        return Artifact.propose(
            type="contract", owner="architect-agent", payload=raw,
            rationale=f"module contract for goal: {goal}",
        )


class PMAgent:
    role = "pm"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, contract: ModuleContract, parent_id: str, lessons: str | None = None) -> Artifact:
        names = ", ".join(f.name for f in contract.functions)
        sigs = "\n".join(f.signature or f.name for f in contract.functions)
        prompt = f"Module functions: {names}\nSignatures:\n{sigs}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=PM_SYSTEM)
        return Artifact.propose(
            type="integration-spec", owner="pm-agent", payload=raw,
            rationale=f"integration criteria for module {contract.module_name}", parent_id=parent_id,
        )


class ModuleDeveloperAgent:
    role = "developer"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, contract: ModuleContract, parent_id: str, lessons: str | None = None) -> Artifact:
        prompt = f"Contract:\n{_contract_to_json(contract)}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=MODULE_DEV_SYSTEM)
        return Artifact.propose(
            type="module-code", owner="developer-agent", payload=_strip_code_fences(raw),
            rationale=f"implements module {contract.module_name}", parent_id=parent_id,
        )


# --- the gates -------------------------------------------------------------------

_CASES_HARNESS = """
import json as _j, os as _o, math as _m
def _eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _m.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b
_t = _j.loads(_o.environ['VERITAS_TRIPLES'])
for _c in _t:
    _fn = globals().get(_c['fn'])
    if _fn is None:
        raise AssertionError(_c['fn'] + '() not defined')
    _g = _fn(*_c['args'])
    if not _eq(_g, _c['expected']):
        raise AssertionError('%s(*%r) -> %r, expected %r' % (_c['fn'], _c['args'], _g, _c['expected']))
print('OK')
"""


def _run_module_cases(
    executor: Executor, code: str, triples: list[dict[str, Any]], timeout: float
) -> tuple[bool, str]:
    if not triples:
        return True, "no cases"
    env = {**os.environ, "VERITAS_TRIPLES": json.dumps(triples)}
    result = executor.run(f"{code}\n{_CASES_HARNESS}", env, timeout)
    if result.ok:
        fns = len({t["fn"] for t in triples})
        return True, f"{len(triples)} cases across {fns} functions pass"
    last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
    return False, last


def _run_snippets(
    executor: Executor, code: str, snippets: list[str], timeout: float
) -> tuple[bool, str]:
    for index, snippet in enumerate(snippets):
        result = executor.run(f"import math\n{code}\n{snippet}\n", {**os.environ}, timeout)
        if not result.ok:
            last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
            return False, f"integration test {index} failed: {last}"
    return True, f"{len(snippets)}/{len(snippets)} integration tests pass"


class ContractGate(Gate):
    name = "contract"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            contract = parse_contract(artifact.payload)
        except ContractParseError as exc:
            return self._result(False, f"contract not usable: {exc}")
        names = ", ".join(f.name for f in contract.functions)
        return self._result(True, f"{len(contract.functions)} functions: {names}")


class IntegrationSpecGate(Gate):
    name = "integration-spec"
    determinism = Determinism.HARD

    def __init__(self, function_names: list[str]) -> None:
        self.function_names = function_names

    def check(self, artifact: Artifact) -> GateResult:
        try:
            tests = parse_integration(artifact.payload)
        except IntegrationParseError as exc:
            return self._result(False, f"integration spec not usable: {exc}")
        touches_two = any(sum(1 for n in self.function_names if n in t) >= 2 for t in tests)
        if not touches_two:
            return self._result(False, "no integration test exercises >= 2 functions together")
        return self._result(True, f"{len(tests)} integration test(s) across the module")


class ModuleSyntaxGate(Gate):
    name = "module-syntax"
    determinism = Determinism.HARD

    def __init__(self, function_names: list[str]) -> None:
        self.function_names = function_names

    def check(self, artifact: Artifact) -> GateResult:
        try:
            tree = ast.parse(artifact.payload)
        except SyntaxError as exc:
            return self._result(False, f"syntax error: {exc}")
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        missing = [fn for fn in self.function_names if fn not in defined]
        if missing:
            return self._result(False, f"missing functions: {', '.join(missing)}")
        return self._result(True, f"all {len(self.function_names)} functions defined")


class ModuleAcceptanceGate(Gate):
    name = "acceptance-tests"
    determinism = Determinism.HARD

    def __init__(self, contract: ModuleContract, executor: Executor | None = None, timeout: float = 10.0) -> None:
        self.contract = contract
        self.executor = executor or _EXEC
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        triples: list[dict[str, Any]] = [
            {"fn": f.name, "args": c.args, "expected": c.expected}
            for f in self.contract.functions
            for c in f.cases
        ]
        passed, evidence = _run_module_cases(self.executor, artifact.payload, triples, self.timeout)
        return self._result(passed, evidence)


class IntegrationGate(Gate):
    """The new boundary: the functions must work TOGETHER, not just alone."""

    name = "integration"
    determinism = Determinism.HARD

    def __init__(self, tests: list[str], executor: Executor | None = None, timeout: float = 10.0) -> None:
        self.tests = tests
        self.executor = executor or _EXEC
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        passed, evidence = _run_snippets(self.executor, artifact.payload, self.tests, self.timeout)
        return self._result(passed, evidence)


# --- the pipeline ----------------------------------------------------------------


@dataclass
class ModuleResult:
    contract_outcome: Outcome
    integration_outcome: Outcome | None  # None if the contract was rejected first
    code_outcome: Outcome | None  # None if contract or integration spec was rejected
    accepted: bool
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build_module(goal: str, provider: ModelProvider, memory: MemoryStore) -> ModuleResult:
    run = Run(goal=goal, memory=memory)
    recalled = memory.recall(goal, categories=["failure", "lesson"], limit=3)
    lessons = format_lessons(recalled)
    informed_by = [record.id for record in recalled]

    # ARCHITECT — design the contract; gate it for usability.
    contract_artifact = ArchitectAgent(provider).propose(goal, lessons=lessons)
    contract_artifact.provenance.informed_by.extend(informed_by)
    contract_outcome = run.submit(contract_artifact, [ContractGate()])
    if not contract_outcome.accepted:
        return ModuleResult(contract_outcome, None, None, False, informed_by, run.id, list(run.log))
    contract = parse_contract(contract_artifact.payload)
    names = [f.name for f in contract.functions]

    # PM — define the integration test against the contract.
    pm_artifact = PMAgent(provider).propose(contract, parent_id=contract_artifact.id, lessons=lessons)
    pm_artifact.provenance.informed_by.extend(informed_by)
    integration_outcome = run.submit(pm_artifact, [IntegrationSpecGate(names)])
    if not integration_outcome.accepted:
        return ModuleResult(contract_outcome, integration_outcome, None, False, informed_by, run.id, list(run.log))
    tests = parse_integration(pm_artifact.payload)

    # DEVELOPER — build the module; the cast (incl. the new integration boundary) reviews it.
    code_artifact = ModuleDeveloperAgent(provider).propose(contract, parent_id=contract_artifact.id, lessons=lessons)
    code_artifact.provenance.informed_by.extend(informed_by)
    code_outcome = run.submit(
        code_artifact,
        [
            ModuleSyntaxGate(names),
            ModuleAcceptanceGate(contract),
            SecurityScanGate(),
            IntegrationGate(tests),
            ValidationGate(),  # final authority — must run last
        ],
    )
    return ModuleResult(
        contract_outcome, integration_outcome, code_outcome, code_outcome.accepted,
        informed_by, run.id, list(run.log),
    )
