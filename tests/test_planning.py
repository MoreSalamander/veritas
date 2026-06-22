"""Cross-org planning — the orchestration layer over the registry.

The planner proposes an ordered {org, goal} plan; a deterministic gate decides if it's runnable;
each step runs through its org's own gates; the plan ships iff every step ships. These tests drive
the orchestration offline (a ScriptedProvider for the planner, fake orgs for execution) so the
plumbing's reliability never depends on a model or a real pipeline being up.
"""

from __future__ import annotations

import json

import pytest

from engine.artifact import Artifact, Determinism
from engine.memory import MemoryStore
from engine.model import ScriptedProvider, SequencedProvider
from orgs import planning
from orgs.planning import (
    Plan,
    PlanScorerGate,
    PlanStep,
    execute_plan,
    gate_plan,
    parse_plan,
    plan_problems,
    propose_plan,
)
from orgs.registry import OrgRun, OrgType


# --- parsing + deterministic gateability ---

def test_parse_plan_reads_ordered_steps():
    raw = '{"steps":[{"org":"research","goal":"the facts"},{"org":"web","goal":"a page"}]}'
    plan = parse_plan("req", raw)
    assert [(s.org, s.goal) for s in plan.steps] == [("research", "the facts"), ("web", "a page")]


def test_plan_problems_flags_every_unrunnable_shape():
    assert plan_problems(Plan("r", [])) == ["the plan has no steps"]
    assert any("unknown studio" in p for p in plan_problems(Plan("r", [PlanStep("nope", "g")])))
    assert any("empty goal" in p for p in plan_problems(Plan("r", [PlanStep("web", "")])))
    assert plan_problems(Plan("r", [PlanStep("web", "a page")])) == []  # runnable -> no problems


def test_plan_scorer_gate_is_hard_and_decides_runnability():
    gate = PlanScorerGate()
    assert gate.determinism is Determinism.HARD
    ok = Artifact.propose(type="plan", owner="t",
                          payload='{"steps":[{"org":"web","goal":"x"}]}', rationale="t")
    assert gate.check(ok).passed
    bad = Artifact.propose(type="plan", owner="t",
                           payload='{"steps":[{"org":"ghost","goal":"x"}]}', rationale="t")
    res = gate.check(bad)
    assert not res.passed and "unknown studio" in res.evidence


# --- the planner self-corrects against the gate ---

def test_propose_plan_accepts_a_runnable_plan():
    good = '{"steps":[{"org":"research","goal":"the facts"},{"org":"web","goal":"a page"}]}'
    plan = propose_plan("a researched landing page", ScriptedProvider({"planner": good}))
    assert plan_problems(plan) == []
    assert [s.org for s in plan.steps] == ["research", "web"]


def test_propose_plan_self_corrects_an_invalid_studio():
    bad = '{"steps":[{"org":"marketing","goal":"x"}]}'  # a studio that doesn't exist
    good = '{"steps":[{"org":"web","goal":"a page"}]}'
    plan = propose_plan("x", SequencedProvider({"planner": [bad, good]}))
    assert plan_problems(plan) == [] and plan.steps[0].org == "web"


def test_gate_plan_reports_runnable_with_evidence():
    runnable, ev = gate_plan(Plan("r", [PlanStep("web", "a page")]))
    assert runnable and "runnable" in ev
    blocked, ev2 = gate_plan(Plan("r", [PlanStep("ghost", "x")]))
    assert not blocked and "not runnable" in ev2


# --- execution orchestration, isolated from real pipelines via fake orgs ---

@pytest.fixture
def fake_orgs(monkeypatch):
    """Swap the registry for cheap fakes so we test the ORCHESTRATION (order, strict-stop,
    ships-iff-all) without spinning real org pipelines."""
    calls: list[tuple[str, str]] = []

    def make(name: str, accept: bool) -> OrgType:
        def build(goal, provider, memory, sources=None):
            calls.append((name, goal))
            return OrgRun(name, goal, accept, [], [], "rid", [])
        return OrgType(name=name, title=name, description="", input_noun="", produces="",
                       verified_by="", goal_hint="", build=build)

    reg = {"a": make("a", True), "b": make("b", True), "x": make("x", False)}
    # plan_problems reads planning.REGISTRY; get_org reads orgs.registry.REGISTRY — patch both.
    monkeypatch.setattr(planning, "REGISTRY", reg)
    monkeypatch.setattr("orgs.registry.REGISTRY", reg)
    return calls


def test_execute_runs_steps_in_order_and_ships_when_all_ship(fake_orgs, tmp_path):
    plan = Plan("r", [PlanStep("a", "g1"), PlanStep("b", "g2")])
    res = execute_plan(plan, ScriptedProvider({}), lambda n: MemoryStore(tmp_path / n))
    assert res.accepted
    assert fake_orgs == [("a", "g1"), ("b", "g2")]  # ran in order
    assert [sr.org for sr in res.step_results] == ["a", "b"]


def test_execute_strict_stops_on_a_failed_step(fake_orgs, tmp_path):
    plan = Plan("r", [PlanStep("a", "g1"), PlanStep("x", "g2"), PlanStep("b", "g3")])
    res = execute_plan(plan, ScriptedProvider({}), lambda n: MemoryStore(tmp_path / n))
    assert not res.accepted
    assert fake_orgs == [("a", "g1"), ("x", "g2")]  # 'b' never ran — the chain stopped
    assert len(res.step_results) == 2


def test_execute_refuses_a_non_runnable_plan_without_running_anything(fake_orgs, tmp_path):
    plan = Plan("r", [PlanStep("ghost", "g")])  # unknown studio
    res = execute_plan(plan, ScriptedProvider({}), lambda n: MemoryStore(tmp_path / n))
    assert not res.accepted and res.problems and fake_orgs == []


def test_execute_passes_each_step_its_own_sources(monkeypatch, tmp_path):
    # a step's pinned sources reach that step's build (and only that step) — so a grounded step
    # has a corpus to cite into, while a non-grounded step gets None.
    seen: list[tuple[str, object]] = []

    def make(name: str) -> OrgType:
        def build(goal, provider, memory, sources=None):
            seen.append((name, sources))
            return OrgRun(name, goal, True, [], [], "rid", [])
        return OrgType(name=name, title=name, description="", input_noun="", produces="",
                       verified_by="", goal_hint="", build=build)

    reg = {"research": make("research"), "web": make("web")}
    monkeypatch.setattr(planning, "REGISTRY", reg)
    monkeypatch.setattr("orgs.registry.REGISTRY", reg)

    plan = Plan("r", [PlanStep("research", "facts", sources=["src A", "src B"]),
                      PlanStep("web", "a page")])
    execute_plan(plan, ScriptedProvider({}), lambda n: MemoryStore(tmp_path / n))
    assert seen == [("research", ["src A", "src B"]), ("web", None)]  # web gets None, not []


# --- typed handoff: a verified report flows to a later grounded step as a corpus ---

_REPORT = json.dumps({"topic": "t", "claims": [
    {"text": "Eagles reach 30 mph", "citations": [{"source": "src1", "quote": "30 mph"}]}]})


def _report_run(goal: str, tmp_path) -> OrgRun:
    from engine.run import Outcome
    art = Artifact.propose(type="report", owner="researcher", payload=_REPORT, rationale="t")
    return OrgRun("research", goal, True, [Outcome(art, True, [], tmp_path / "m")], [], "rid", [])


def test_corpus_from_run_extracts_only_grounded_output():
    from orgs.planning import corpus_from_run
    assert corpus_from_run(_report_run("g", __import__("pathlib").Path("/tmp"))) == ["Eagles reach 30 mph"]
    # a non-report artifact has no downstream gate to verify a handoff -> contributes nothing
    from engine.run import Outcome
    code = Artifact.propose(type="code", owner="dev", payload="x", rationale="t")
    run = OrgRun("software", "g", True, [Outcome(code, True, [], __import__("pathlib").Path("/tmp"))], [], "r", [])
    assert corpus_from_run(run) == []


def test_handoff_feeds_a_verified_report_into_a_later_grounded_step(monkeypatch, tmp_path):
    received: dict[str, object] = {}

    def research_build(goal, provider, memory, sources=None):
        received[goal] = sources
        return _report_run(goal, tmp_path)

    reg = {"research": OrgType(name="research", title="r", description="", input_noun="",
                               produces="", verified_by="", goal_hint="", build=research_build,
                               needs_sources=True)}
    monkeypatch.setattr(planning, "REGISTRY", reg)
    monkeypatch.setattr("orgs.registry.REGISTRY", reg)

    plan = Plan("r", [PlanStep("research", "step one", sources=["a human source"]),
                      PlanStep("research", "step two")])  # no human sources of its own
    execute_plan(plan, ScriptedProvider({}), lambda n: MemoryStore(tmp_path / n))

    assert received["step one"] == ["a human source"]          # handoff was empty before step one ran
    assert received["step two"] == ["Eagles reach 30 mph"]     # step two cites step one's verified claim
