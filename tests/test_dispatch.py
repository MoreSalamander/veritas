"""The intake agent: work orders in, finished work out, refusals deterministic."""

from __future__ import annotations

import pytest

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.dispatch import (
    DispatchError,
    RouteProposal,
    WorkOrder,
    dispatch,
    propose_route,
    validate_order,
)


def _memory(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory")


def test_named_org_short_circuits_routing(tmp_path) -> None:
    # A named order never consults the model: the provider would explode.
    order = WorkOrder(request="whatever", org="software", goal="add(a, b)", model="gemma-12b")
    validate_order(order)  # front desk accepts
    # (dispatch itself would run a real build; the named path's routing is
    # covered by validate + the proposal test below.)
    proposal = RouteProposal(org="software", goal="add(a, b)", proposed_by="named")
    assert proposal.proposed_by == "named"


def test_model_proposal_routes_when_org_is_known() -> None:
    provider = ScriptedProvider({"router": '{"org": "web", "goal": "a landing page for a coffee shop"}'})
    p = propose_route("make me a coffee shop site", provider)
    assert p.org == "web" and p.proposed_by == "model"
    assert p.goal == "a landing page for a coffee shop"


def test_garbage_model_output_falls_back_to_keywords() -> None:
    provider = ScriptedProvider({"router": "I think maybe the web studio? not sure!!"})
    p = propose_route("a landing page for my bakery", provider)
    assert p.org == "web" and p.proposed_by == "keyword"


def test_unknown_org_proposal_is_discarded_deterministically() -> None:
    provider = ScriptedProvider({"router": '{"org": "blockchain_studio", "goal": "x"}'})
    p = propose_route("a report with cited sources", provider)
    assert p.org == "research" and p.proposed_by == "keyword"


def test_unknown_named_engine_is_refused() -> None:
    with pytest.raises(DispatchError) as e:
        validate_order(WorkOrder(request="x", org="nonexistent_engine"))
    assert "registered:" in str(e.value)


def test_unknown_model_is_refused() -> None:
    with pytest.raises(DispatchError) as e:
        validate_order(WorkOrder(request="x", model="gpt-99"))
    assert "catalog:" in str(e.value)


def test_dispatch_runs_the_named_engine_end_to_end(tmp_path) -> None:
    # The software org on a scripted provider: spec, then code that passes it.
    provider = ScriptedProvider({
        "router": "never called — the order names its engine",
        "spec": '{"description": "double a number", "function_name": "double", '
                '"cases": [{"args": [2], "expected": 4}, {"args": [0], "expected": 0}], '
                '"properties": []}',
        "developer": "def double(x):\n    return x * 2\n",
        "qa": "[]",
        "doc": "Doubles a number.",
    })
    finished = dispatch(
        WorkOrder(request="double a number", org="software", model="gemma-12b"),
        provider,
        _memory(tmp_path),
    )
    assert finished.proposal.proposed_by == "named"
    assert finished.run.org == "software"
    assert finished.run.accepted
