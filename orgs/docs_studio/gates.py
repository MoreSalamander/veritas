"""The docs gates — the decision engine for documents.

  outline-scorer  HARD  the outline is usable (gates the outline)
  structure       HARD  the doc has every required section + enough examples
  examples-run    HARD  EVERY code example actually executes (reuses the Executor)
  readability     SOFT  a thin-content heuristic — advisory, never a block

The star is examples-run: it reuses the very same engine.Executor the software studio
uses, which is the vivid proof that the substrate is shared, not copied.
"""

from __future__ import annotations

import os

from engine.artifact import Artifact, Determinism, GateResult
from engine.executor import Executor, LocalSubprocessExecutor
from engine.gate import Gate
from orgs.docs_studio.spec import (
    DocsSpec,
    DocsSpecParseError,
    extract_python_blocks,
    parse_docs_spec,
    strip_code_blocks,
)

_DEFAULT_EXECUTOR = LocalSubprocessExecutor()


class OutlineScorerGate(Gate):
    name = "outline-scorer"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            spec = parse_docs_spec(artifact.payload)
        except DocsSpecParseError as exc:
            return self._result(False, f"outline not usable: {exc}")
        return self._result(
            True,
            f"{len(spec.sections)} section(s); >= {spec.min_examples} runnable example(s) required",
        )


class StructureGate(Gate):
    name = "structure"
    determinism = Determinism.HARD

    def __init__(self, spec: DocsSpec) -> None:
        self.spec = spec

    def check(self, artifact: Artifact) -> GateResult:
        doc = artifact.payload
        headings = [line for line in doc.splitlines() if line.lstrip().startswith("#")]
        missing = [
            s for s in self.spec.sections if not any(s.lower() in h.lower() for h in headings)
        ]
        blocks = extract_python_blocks(doc)
        problems: list[str] = []
        if missing:
            problems.append("missing sections: " + ", ".join(missing))
        if len(blocks) < self.spec.min_examples:
            problems.append(f"{len(blocks)} example(s), need {self.spec.min_examples}")
        if problems:
            return self._result(False, "; ".join(problems))
        return self._result(
            True, f"all {len(self.spec.sections)} section(s) present, {len(blocks)} example(s)"
        )


class ExamplesRunGate(Gate):
    """Every fenced python example must execute cleanly, through the shared Executor."""

    name = "examples-run"
    determinism = Determinism.HARD

    def __init__(self, executor: Executor | None = None, timeout: float = 10.0) -> None:
        self.executor = executor or _DEFAULT_EXECUTOR
        self.timeout = timeout

    def check(self, artifact: Artifact) -> GateResult:
        blocks = extract_python_blocks(artifact.payload)
        if not blocks:
            return self._result(False, "no python examples to verify")
        for index, block in enumerate(blocks):
            result = self.executor.run(block, {**os.environ}, self.timeout)
            if not result.ok:
                last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "non-zero exit"
                return self._result(False, f"example {index} failed: {last}")
        return self._result(True, f"{len(blocks)}/{len(blocks)} examples ran")


class ReadabilityGate(Gate):
    """A thin-content heuristic. SOFT — it's a proxy for 'is this actually explained?',
    not a proof, so it advises and never blocks."""

    name = "readability"
    determinism = Determinism.SOFT

    def __init__(self, min_words: int = 25) -> None:
        self.min_words = min_words

    def check(self, artifact: Artifact) -> GateResult:
        prose = strip_code_blocks(artifact.payload)
        words = len(prose.split())
        if words < self.min_words:
            return self._result(False, f"thin: only {words} words of prose (advisory)")
        return self._result(True, f"{words} words of prose")
