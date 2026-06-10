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
from orgs.software_studio.spec import SpecData, SpecParseError, parse_spec

# Data is never interpolated into source — cases ride as JSON through the
# environment and are looped over. Immune to quoting/injection from spec values
# (the lesson from the first real run).
_HARNESS = (
    "\nimport json as _json, os as _os\n"
    '_cases = _json.loads(_os.environ["VERITAS_CASES"])\n'
    '_fn = globals().get(_os.environ["VERITAS_FN"])\n'
    "if _fn is None:\n"
    '    raise AssertionError(_os.environ["VERITAS_FN"] + "() not found at module scope")\n'
    "for _i, _c in enumerate(_cases):\n"
    '    _got = _fn(*_c["args"])\n'
    '    if _got != _c["expected"]:\n'
    '        raise AssertionError("case %d: %s(*%r) -> %r, expected %r" % (\n'
    '            _i, _os.environ["VERITAS_FN"], _c["args"], _got, _c["expected"]))\n'
    'print("OK", len(_cases), "cases")\n'
)


_DEFAULT_EXECUTOR = LocalSubprocessExecutor()


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
            True, f"{len(spec.cases)} executable case(s) pin {spec.function_name}()"
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
    name = "acceptance-tests"
    determinism = Determinism.HARD

    def __init__(
        self, spec: SpecData, executor: Executor | None = None, timeout: float = 10.0
    ) -> None:
        self.spec = spec
        self.executor = executor or _DEFAULT_EXECUTOR
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        cases = [{"args": c.args, "expected": c.expected} for c in self.spec.cases]
        passed, evidence = _run_cases(
            self.executor, artifact.payload, self.spec.function_name, cases, self.timeout
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


class ValidationGate(Gate):
    """Final authority. Inspects the artifact's accumulated provenance and confirms
    every HARD gate passed and provenance is complete. No artifact enters memory
    without this approval — Validation has the final say."""

    name = "validation"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        prior = artifact.provenance.gate_results  # all gates recorded before this one
        if not artifact.provenance.created_by or not artifact.provenance.rationale:
            return self._result(False, "withheld — incomplete provenance (owner/rationale)")
        hard = [r for r in prior if r.determinism is Determinism.HARD]
        if not hard:
            return self._result(False, "withheld — no hard verification to validate")
        failed = [r for r in hard if not r.passed]
        if failed:
            return self._result(
                False, "withheld — hard gate(s) failed: " + ", ".join(r.gate_name for r in failed)
            )
        soft_findings = [r for r in prior if r.determinism is Determinism.SOFT and not r.passed]
        note = f"approved — {len(hard)} hard check(s) passed"
        if soft_findings:
            note += f", {len(soft_findings)} soft finding(s) noted"
        return self._result(True, note)
