"""P30 — the trust benchmark: does the deterministic gate architecture refuse plausible-but-wrong
outputs that a bare agent (same model, no gates) ships?

The comparison is scientifically clean: both contestants get the SAME model; the only variable is
Veritas's gate+retry architecture.

  - bare agent : one model proposal, shipped as-is (no gates, no retry) — the naive baseline.
  - veritas    : the same model, proposed through `build_function` (spec-scorer + oracle-free
                 property gate + retry); ships ONLY on accept.

The judge is INDEPENDENT of both: held-out reference cases that neither contestant ever sees. This is
what keeps the benchmark from being circular — Veritas's own gates never decide what "correct" means
here; an outside oracle does. The honest split: a task is `catchable` if its failure class is
expressible as an oracle-free gate. For the *un*catchable class (a pure value error no relation pins —
the documented a+b vs a-b limit) Veritas also ships, but flags it soft rather than false-greening; the
report counts both classes so the result is honest, not propaganda.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from engine.executor import Executor, LocalSubprocessExecutor
from engine.memory import MemoryStore
from engine.model import ModelProvider
from orgs.software_studio.agents import _strip_code_fences
from orgs.software_studio.pipeline import build_function


@dataclass
class TrustTask:
    name: str
    goal: str
    fn_name: str
    reference_cases: list[tuple[list[Any], Any]]  # the HIDDEN judge: (args, expected)
    catchable: bool = True  # is this failure class expressible as an oracle-free gate?


class Verdict(Enum):
    SHIPPED_CORRECT = "shipped-correct"
    SHIPPED_WRONG = "shipped-wrong"    # FALSE SHIP — presented as done, but wrong
    REFUSED_GOOD = "refused-good"      # refused, and it really was wrong
    REFUSED_OVER = "refused-over"      # OVER-REFUSAL — refused, but it would have been correct
    NO_OUTPUT = "no-output"            # produced nothing runnable


_JUDGE_HARNESS = '''{code}

import json, os
_cases = json.loads(os.environ["TRUST_CASES"])
_fn = {fn}
for _args, _expected in _cases:
    try:
        _got = _fn(*_args)
    except Exception:
        print("JUDGE_FAIL"); raise SystemExit(0)
    if _got != _expected:
        print("JUDGE_FAIL"); raise SystemExit(0)
print("JUDGE_OK")
'''


def _defined_fn_name(code: str, preferred: str) -> str | None:
    """The function the code actually defines — by BEHAVIOR, not a fixed name. Models rename freely
    (gemma turned `negate` into `get_additive_inverse`); the judge must call whatever was defined, or
    it falsely scores correct code as wrong. Prefer the task's name if present, else the last top-level
    def (the entry point, after any helpers)."""
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not names:
        return None
    return preferred if preferred in names else names[-1]


def judge(code: str | None, task: TrustTask, executor: Executor) -> bool | None:
    """The independent oracle: run the candidate against the HIDDEN reference cases. True = correct,
    False = wrong/errored, None = nothing to judge. Cases travel as a JSON env var (injection-safe)."""
    if not code or not code.strip():
        return None
    fn = _defined_fn_name(code, task.fn_name)
    if fn is None:
        return False  # nothing callable was defined → not correct
    harness = _JUDGE_HARNESS.format(code=code, fn=fn)
    env = {"TRUST_CASES": json.dumps(task.reference_cases), "PATH": os.environ.get("PATH", "")}
    res = executor.run(harness, env=env, timeout=10)
    if "JUDGE_OK" in res.stdout:
        return True
    return False  # JUDGE_FAIL, an exception, or no clean run → not correct


@dataclass
class Trial:
    shipped: bool        # did the contestant present an answer as done?
    code: str | None     # the code it produced (judged whether shipped or refused)


def run_bare(task: TrustTask, provider: ModelProvider) -> Trial:
    """Bare agent: one proposal, shipped as-is. No gates — the realistic 'just ask the model' use."""
    prompt = (f"Write a Python function `{task.fn_name}` that: {task.goal}. "
              f"Return only the function definition.")
    return Trial(shipped=True, code=_strip_code_fences(provider.propose(role="developer", prompt=prompt)))


def run_veritas(task: TrustTask, provider: ModelProvider, memory: MemoryStore) -> Trial:
    """Veritas: the same model proposed through the gate+retry architecture; ships only on accept."""
    res = build_function(task.goal, provider, memory)
    code = res.code_outcome.artifact.payload if res.code_outcome is not None else None
    return Trial(shipped=res.accepted, code=code)


def run_gate_isolation(spec_json: str, task: TrustTask, provider: ModelProvider,
                       parent_id: str = "iso") -> tuple[Trial, Trial]:
    """The clean experiment: both contestants get the SAME correct spec AND the SAME single code
    proposal — only the gates differ. The model writes the implementation once; the bare agent ships
    that exact code ungated, Veritas runs the spec's hard gates over it. Removes the property-authoring
    confound (the spec, with its catching property, is given) so the result isolates the gates alone."""
    from orgs.software_studio.agents import DeveloperAgent
    from orgs.software_studio.gates import PropertyGate, SyntaxGate
    from orgs.software_studio.spec import parse_spec

    spec = parse_spec(spec_json)
    art = DeveloperAgent(provider).propose(spec, parent_id=parent_id)  # one proposal, shared
    code = art.payload
    bare = Trial(shipped=True, code=code)  # ship the proposal ungated
    hard_pass = (SyntaxGate(spec.function_name).check(art).passed
                 and PropertyGate(spec.function_name, spec.properties).check(art).passed)
    veritas = Trial(shipped=hard_pass, code=code)  # the SAME code, now gated
    return bare, veritas


def classify(task: TrustTask, trial: Trial, executor: Executor) -> Verdict:
    correct = judge(trial.code, task, executor)
    if trial.shipped:
        if correct is None:
            return Verdict.NO_OUTPUT
        return Verdict.SHIPPED_CORRECT if correct else Verdict.SHIPPED_WRONG
    return Verdict.REFUSED_OVER if correct is True else Verdict.REFUSED_GOOD


@dataclass
class Report:
    contestant: str
    verdicts: dict[Verdict, int] = field(default_factory=dict)
    n: int = 0

    def add(self, v: Verdict) -> None:
        self.verdicts[v] = self.verdicts.get(v, 0) + 1
        self.n += 1

    def count(self, v: Verdict) -> int:
        return self.verdicts.get(v, 0)

    @property
    def false_ship_rate(self) -> float:
        return self.count(Verdict.SHIPPED_WRONG) / self.n if self.n else 0.0

    @property
    def over_refusal_rate(self) -> float:
        return self.count(Verdict.REFUSED_OVER) / self.n if self.n else 0.0


@dataclass
class BatteryResult:
    bare: Report
    veritas: Report
    records: list[tuple[str, bool, Verdict, Verdict]] = field(  # (task, catchable, bare, veritas)
        default_factory=list)

    def catchable_false_ships(self) -> tuple[int, int]:
        """(bare, veritas) false-ship counts within the CATCHABLE class — the headline comparison."""
        b = sum(1 for _, c, bv, _ in self.records if c and bv == Verdict.SHIPPED_WRONG)
        v = sum(1 for _, c, _, vv in self.records if c and vv == Verdict.SHIPPED_WRONG)
        return b, v


def run_battery(
    items: list[tuple[TrustTask, ModelProvider]],
    memory_factory: Callable[[], MemoryStore],
    executor: Executor | None = None,
) -> BatteryResult:
    """Run each (task, provider) through both contestants and the independent judge. One provider
    serves all tasks for a real model; per-task providers let offline tests script each outcome."""
    ex = executor or LocalSubprocessExecutor()
    out = BatteryResult(Report("bare-agent"), Report("veritas"))
    for task, provider in items:
        bare_v = classify(task, run_bare(task, provider), ex)
        ver_v = classify(task, run_veritas(task, provider, memory_factory()), ex)
        out.bare.add(bare_v)
        out.veritas.add(ver_v)
        out.records.append((task.name, task.catchable, bare_v, ver_v))
    return out
