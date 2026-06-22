"""P7 — one front door routes function vs module; the hub rides on it."""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import OllamaProvider, ScriptedProvider
from orgs.software_studio.builder import build

SPEC = json.dumps(
    {"function_name": "add", "description": "add", "signature": "def add(a, b)",
     "cases": [{"args": [1, 2], "expected": 3}]}
)
CODE = "def add(a, b):\n    return a + b\n"
DOC = "# add\n\n```python\nassert add(2, 3) == 5\n```\n"

CONTRACT = json.dumps(
    {"module_name": "temp", "functions": [
        {"function_name": "c2f", "signature": "def c2f(c)", "cases": [{"args": [0], "expected": 32}]},
        {"function_name": "f2c", "signature": "def f2c(f)", "cases": [{"args": [32], "expected": 0}]},
    ]}
)
PM = json.dumps(["assert abs(f2c(c2f(100)) - 100) < 1e-9"])
MODULE = "def c2f(c):\n    return c * 9 / 5 + 32\n\ndef f2c(f):\n    return (f - 32) * 5 / 9\n"


def test_routes_to_function_and_documents(tmp_path):
    provider = ScriptedProvider({"router": "function", "spec": SPEC, "developer": CODE, "qa": "[]", "doc": DOC})
    result = build("add two numbers", provider, MemoryStore(tmp_path))
    assert result.shape == "function" and result.accepted
    assert [o.artifact.type for o in result.outcomes] == ["spec", "code", "documentation"]


def test_routes_to_module(tmp_path):
    provider = ScriptedProvider({"router": "module", "architect": CONTRACT, "pm": PM, "developer": MODULE})
    result = build("a temperature module", provider, MemoryStore(tmp_path))
    assert result.shape == "module" and result.accepted
    assert [o.artifact.type for o in result.outcomes] == ["contract", "integration-spec", "module-code"]


def test_router_defaults_to_function_when_unavailable(tmp_path):
    # No "router" role -> classify falls back to the simpler shape, build still works.
    provider = ScriptedProvider({"spec": SPEC, "developer": CODE, "qa": "[]", "doc": DOC})
    result = build("add", provider, MemoryStore(tmp_path))
    assert result.shape == "function" and result.accepted


def test_explicit_shape_overrides_router(tmp_path):
    provider = ScriptedProvider({"architect": CONTRACT, "pm": PM, "developer": MODULE})
    result = build("anything", provider, MemoryStore(tmp_path), shape="module")
    assert result.shape == "module" and result.accepted


def test_routes_to_app(tmp_path):
    from engine.model import SequencedProvider

    plan = json.dumps({"app_name": "store", "modules": [
        {"module_name": "storage", "goal": "save and load"},
        {"module_name": "ops", "goal": "add and confirm"}]})
    c1 = json.dumps({"module_name": "storage", "functions": [
        {"function_name": "save", "signature": "def save(x)", "cases": [{"args": [5], "expected": 5}]},
        {"function_name": "load", "signature": "def load(x)", "cases": [{"args": [5], "expected": 5}]}]})
    c2 = json.dumps({"module_name": "ops", "functions": [
        {"function_name": "add", "signature": "def add(a, b)", "cases": [{"args": [1, 1], "expected": 2}]},
        {"function_name": "confirm", "signature": "def confirm(x)", "cases": [{"args": [1], "expected": True}]}]})
    provider = SequencedProvider({
        "router": ["app"],
        "planner": [plan],
        "architect": [c1, c2],
        "pm": [json.dumps(["assert load(save(7)) == 7"]),
               json.dumps(["assert confirm(add(1, 1)) == True"]),
               json.dumps(["assert main(1) == True"])],
        "developer": ["def save(x):\n    return x\n\ndef load(x):\n    return x\n",
                      "def add(a, b):\n    return a + b\n\ndef confirm(x):\n    return True\n"],
        "integrator": ["def main(x):\n    return confirm(add(load(save(x)), 1))\n"],
    })
    result = build("a tiny store app", provider, MemoryStore(tmp_path))
    assert result.shape == "app" and result.accepted
    assert [o.artifact.type for o in result.outcomes] == ["plan", "package", "entrypoint", "e2e-spec"]


# --- adaptive thinking: the proposer is re-tuned for the routed shape ---

def test_ollama_for_shape_toggles_thinking():
    base = OllamaProvider(model="gemma4:12b", think=False)
    assert base.for_shape("function") is base            # functions stay direct
    for hard in ("module", "app"):
        tuned = base.for_shape(hard)                      # harder shapes turn thinking ON
        assert isinstance(tuned, OllamaProvider) and tuned.think is True and tuned.model == base.model
    thinker = OllamaProvider(model="gemma4:12b", think=True)
    assert thinker.for_shape("module") is thinker         # already correct -> no needless rebuild


class _RecordingProvider(ScriptedProvider):
    """Behaves like ScriptedProvider but records the shape build() asks it to tune for."""

    def __init__(self, by_role):
        super().__init__(by_role)
        self.shaped: list[str] = []

    def for_shape(self, shape):
        self.shaped.append(shape)
        return self


def test_retry_budget_caps_thinking_lower():
    # off-thinking keeps the full budget (cheap, useful retries); thinking caps to 2 (slow,
    # rarely-paying retries). Cloud / scripted providers use the default.
    assert OllamaProvider(model="gemma4:12b", think=False).retry_budget() == 3
    assert OllamaProvider(model="gemma4:12b", think=True).retry_budget() == 2
    assert ScriptedProvider({}).retry_budget() == 3


def test_run_honours_its_max_attempts_budget(tmp_path):
    # a Run built with a capped budget stops retrying at that limit (proves the budget flows from
    # the provider into the loop). An always-failing hard gate exhausts the cap.
    from engine.artifact import Artifact, Determinism, GateResult
    from engine.gate import Gate
    from engine.run import Run

    class AlwaysFail(Gate):
        name = "always-fail"
        determinism = Determinism.HARD

        def check(self, artifact: Artifact) -> GateResult:
            return self._result(False, "no")

    run = Run(goal="g", memory=MemoryStore(tmp_path), max_attempts=2)
    attempts = {"n": 0}

    def propose(_fb):
        attempts["n"] += 1
        return Artifact.propose(type="code", owner="dev", payload="x", rationale="t")

    run.attempt(propose, [AlwaysFail()])
    assert attempts["n"] == 2  # capped at the Run's budget, not the default 3


def test_build_retunes_provider_for_the_routed_shape(tmp_path):
    mod = _RecordingProvider({"router": "module", "architect": CONTRACT, "pm": PM, "developer": MODULE})
    build("a temperature module", mod, MemoryStore(tmp_path))
    assert mod.shaped == ["module"]  # re-tuned for the module shape after routing

    fn = _RecordingProvider({"router": "function", "spec": SPEC, "developer": CODE, "qa": "[]", "doc": DOC})
    build("add two numbers", fn, MemoryStore(tmp_path))
    assert fn.shaped == ["function"]
