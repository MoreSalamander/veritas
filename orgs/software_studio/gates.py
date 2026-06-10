"""The gates — the decision engine for software artifacts. All deterministic.

- SpecScorerGate : the spec must be executable, or it's rejected before any code.
- SyntaxGate     : the code must parse and actually define the function.
- AcceptanceGate : the code must pass every case the spec pinned down.

None of these ask an LLM anything. That is the whole point — the green is earned
by machine-checkable facts, not by a confident sentence.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from orgs.software_studio.spec import SpecData, SpecParseError, parse_spec


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
    """Runs the candidate code against the spec's cases in an isolated subprocess
    (with a timeout, since model code can loop). Pass iff every case holds.

    Subprocess isolation is the floor of safety here; real sandboxing of
    model-generated code is a later hardening pass, noted in the roadmap."""

    name = "acceptance-tests"
    determinism = Determinism.HARD

    # Data is never interpolated into source — the cases are passed as JSON through
    # the environment and looped over. This keeps the harness immune to quoting and
    # injection from spec values (the lesson from the first real run).
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

    def __init__(self, spec: SpecData, timeout: float = 10.0) -> None:
        self.spec = spec
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        cases = [{"args": c.args, "expected": c.expected} for c in self.spec.cases]
        env = {
            **os.environ,
            "VERITAS_CASES": json.dumps(cases),
            "VERITAS_FN": self.spec.function_name,
        }
        script = f"{artifact.payload}\n{self._HARNESS}"
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return self._result(False, f"timed out after {self.timeout}s")

        total = len(self.spec.cases)
        if proc.returncode == 0:
            return self._result(True, f"{total}/{total} cases passed")

        last = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "non-zero exit"
        return self._result(False, last)
