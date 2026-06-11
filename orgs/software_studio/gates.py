"""The gates — the decision engine for software artifacts.

The cast's verdicts, as gates on the code artifact:

  spec-scorer      HARD  the spec must be executable (gates the spec, not the code)
  syntax           HARD  the code parses and defines the function
  acceptance-tests HARD  the code passes the spec's cases
  security-scan    HARD  no dangerous calls (deterministic static scan, no LLM)
  qa-review        SOFT  an independent reviewer — advisory, never a hard block
  validation       HARD  final authority: every hard gate passed, provenance complete

Every hard gate is machine-checkable and asks no LLM anything. The one soft gate
(QA) is honestly marked soft because its oracle is itself an LLM proposal.
"""

from __future__ import annotations

import ast
import json
import os
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.executor import Executor, LocalSubprocessExecutor
from engine.gate import Gate
from orgs.software_studio.properties import (
    PROPERTY_HARNESS,
    Property,
    serialize,
)
from orgs.software_studio.spec import (
    SpecData,
    SpecParseError,
    extract_python_blocks,
    parse_spec,
)

# Data is never interpolated into source — cases ride as JSON through the
# environment and are looped over. Immune to quoting/injection from spec values
# (the lesson from the first real run).
_HARNESS = """
import json as _json, os as _os, math as _math
def _eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b
_cases = _json.loads(_os.environ["VERITAS_CASES"])
_fn = globals().get(_os.environ["VERITAS_FN"])
if _fn is None:
    raise AssertionError(_os.environ["VERITAS_FN"] + "() not found at module scope")
for _i, _c in enumerate(_cases):
    _got = _fn(*_c["args"])
    if not _eq(_got, _c["expected"]):
        raise AssertionError("case %d: %s(*%r) -> %r, expected %r" % (
            _i, _os.environ["VERITAS_FN"], _c["args"], _got, _c["expected"]))
print("OK", len(_cases), "cases")
"""


_DEFAULT_EXECUTOR = LocalSubprocessExecutor()


def run_properties(
    executor: Executor,
    code: str,
    function_name: str,
    properties: list[Property],
    timeout: float,
) -> tuple[bool, str]:
    """Run oracle-free properties for one function against `code` (which may define its
    siblings too — so round_trip's inverse is in scope at the module/app level).
    Deterministic given the same code+properties; no model value is ever the oracle."""
    if not properties:
        return True, "no oracle-free properties offered — behavior not hard-verified"
    env = {**os.environ, "VERITAS_PROPS": serialize(properties), "VERITAS_FN": function_name}
    result = executor.run(f"{code}\n{PROPERTY_HARNESS}", env, timeout)
    if result.ok:
        held = "; ".join(p.describe() for p in properties)
        return True, f"{len(properties)} oracle-free property(ies) hold: {held}"
    last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
    return False, last


def _run_cases(
    executor: Executor,
    code: str,
    function_name: str,
    cases: list[dict[str, Any]],
    timeout: float,
) -> tuple[bool, str]:
    """Run `cases` against `code` through the execution boundary. Deterministic given
    the same code+cases. The executor is what makes this hosting-safe later."""
    if not cases:
        return True, "no cases to run"
    env = {**os.environ, "VERITAS_CASES": json.dumps(cases), "VERITAS_FN": function_name}
    result = executor.run(f"{code}\n{_HARNESS}", env, timeout)
    if result.ok:
        return True, f"{len(cases)}/{len(cases)} cases passed"
    last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
    return False, last


class SpecScorerGate(Gate):
    name = "spec-scorer"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            spec = parse_spec(artifact.payload)
        except SpecParseError as exc:
            return self._result(False, f"spec not executable: {exc}")
        return self._result(
            True,
            f"{len(spec.cases)} case(s) + {len(spec.properties)} oracle-free "
            f"property(ies) pin {spec.function_name}()",
        )


class SyntaxGate(Gate):
    name = "syntax"
    determinism = Determinism.HARD

    def __init__(self, function_name: str) -> None:
        self.function_name = function_name

    def check(self, artifact: Artifact) -> GateResult:
        try:
            tree = ast.parse(artifact.payload)
        except SyntaxError as exc:
            return self._result(False, f"syntax error: {exc}")
        defined = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == self.function_name
            for node in ast.walk(tree)
        )
        if not defined:
            return self._result(False, f"{self.function_name}() is not defined")
        return self._result(True, f"parses clean; {self.function_name}() defined")


class AcceptanceGate(Gate):
    """Runs the spec's exact-value cases. SOFT (P13): an `expected` value is a number
    the *model* wrote — an unverified oracle. A hard gate must never accept (or reject)
    on the model's arithmetic, so a case discrepancy is an advisory finding, not a
    block. The oracle-free PropertyGate is the hard behavioral authority."""

    name = "acceptance-tests"
    determinism = Determinism.SOFT

    def __init__(
        self, spec: SpecData, executor: Executor | None = None, timeout: float = 10.0
    ) -> None:
        self.spec = spec
        self.executor = executor or _DEFAULT_EXECUTOR
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        if not self.spec.cases:
            return self._result(True, "no exact-value cases offered")
        cases = [{"args": c.args, "expected": c.expected} for c in self.spec.cases]
        passed, evidence = _run_cases(
            self.executor, artifact.payload, self.spec.function_name, cases, self.timeout
        )
        if passed:
            return self._result(True, evidence)
        return self._result(
            False, f"case discrepancy (advisory, model-authored oracle): {evidence}"
        )


class PropertyGate(Gate):
    """HARD: oracle-free properties (round-trips, idempotence, monotonicity, structural
    invariants). Each checks a relation over the function's OWN outputs — no model value
    is the oracle, so a pass is the scaffold's verdict, not the model's. With no
    properties offered, it passes but records that behavior was not hard-verified — the
    architecture stays honest about what it could and could not guarantee."""

    name = "properties"
    determinism = Determinism.HARD

    def __init__(
        self,
        function_name: str,
        properties: list[Property],
        executor: Executor | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.function_name = function_name
        self.properties = properties
        self.executor = executor or _DEFAULT_EXECUTOR
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        passed, evidence = run_properties(
            self.executor, artifact.payload, self.function_name, self.properties, self.timeout
        )
        return self._result(passed, evidence)


class SecurityScanGate(Gate):
    """Deterministic static scan for dangerous calls. No oracle, no LLM — the
    Security agent IS the scan."""

    name = "security-scan"
    determinism = Determinism.HARD

    _DANGEROUS_NAMES = {"eval", "exec", "compile", "__import__"}

    def check(self, artifact: Artifact) -> GateResult:
        try:
            tree = ast.parse(artifact.payload)
        except SyntaxError as exc:
            return self._result(False, f"unparseable: {exc}")
        findings: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in self._DANGEROUS_NAMES:
                findings.append(f"{func.id}()")
            elif isinstance(func, ast.Attribute):
                if func.attr in {"system", "popen"}:
                    findings.append(f"{func.attr}()")
                elif (
                    func.attr == "loads"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "pickle"
                ):
                    findings.append("pickle.loads()")
        if findings:
            return self._result(False, "dangerous call(s): " + ", ".join(sorted(set(findings))))
        return self._result(
            True, "clean (scanned eval/exec/compile/__import__/os.system/os.popen/pickle.loads)"
        )


class QAGate(Gate):
    """Independent QA: runs QA-proposed cases against the code. SOFT, because QA's
    expected values are themselves an LLM proposal — an unverified oracle. A QA
    discrepancy is recorded as a finding for humans, never a hard block."""

    name = "qa-review"
    determinism = Determinism.SOFT

    def __init__(
        self,
        function_name: str,
        cases: list[dict[str, Any]],
        executor: Executor | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.function_name = function_name
        self.cases = cases
        self.executor = executor or _DEFAULT_EXECUTOR
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        if not self.cases:
            return self._result(True, "QA produced no usable independent cases")
        passed, evidence = _run_cases(
            self.executor, artifact.payload, self.function_name, self.cases, self.timeout
        )
        if passed:
            return self._result(True, f"QA: {len(self.cases)} independent case(s) consistent")
        return self._result(
            False, f"QA flagged a discrepancy (advisory, oracle unverified): {evidence}"
        )


class ExamplesRunGate(Gate):
    """Every fenced python example in a doc must execute cleanly. When a `preamble`
    is given (the documented function's source), each example runs WITH the function
    in scope — so the documentation's examples are verified against the real code,
    not a redefinition. This is what lets docs live in the software org: they're
    checked by executing code, the same verification model as the code itself."""

    name = "examples-run"
    determinism = Determinism.HARD

    def __init__(
        self,
        executor: Executor | None = None,
        timeout: float = 10.0,
        preamble: str = "",
        must_reference: str | None = None,
    ) -> None:
        self.executor = executor or _DEFAULT_EXECUTOR
        self.timeout = timeout
        self.preamble = preamble
        self.must_reference = must_reference

    def check(self, artifact: Artifact) -> GateResult:
        blocks = extract_python_blocks(artifact.payload)
        if not blocks:
            return self._result(False, "no python examples to verify")
        if self.must_reference and not any(self.must_reference in b for b in blocks):
            return self._result(False, f"no example demonstrates {self.must_reference}()")
        for index, block in enumerate(blocks):
            script = f"{self.preamble}\n{block}" if self.preamble else block
            result = self.executor.run(script, {**os.environ}, self.timeout)
            if not result.ok:
                last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
                return self._result(False, f"example {index} failed: {last}")
        scope = " against the function" if self.preamble else ""
        return self._result(True, f"{len(blocks)}/{len(blocks)} examples ran{scope}")


# ValidationGate is org-agnostic and now lives in engine.validation (shared substrate).
