"""The Plan tab — cross-org planning end to end through the hub.

The planner proposes a runnable plan, the human confirms over HTTP (the review callback blocks on
an Event), and each step executes through its org's gates — all driven offline with a scripted
provider. Software-only steps keep it fast and deterministic; the orchestration is the same for any
org. The engine functions (`propose_plan`, `execute_plan`) are unchanged; the hub just turns their
blocking review into a turn-based web conversation.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider
from hub.app import create_app

SPEC = json.dumps(
    {"function_name": "add", "description": "add", "signature": "def add(a, b)",
     "cases": [{"args": [1, 2], "expected": 3}]}
)
CODE = "def add(a, b):\n    return a + b\n"
DOC = "# add\n\n```python\nassert add(2, 3) == 5\n```\n"


def _provider(plan_json: str) -> ScriptedProvider:
    # planner returns the plan; the rest are the software org's roles so each step really builds.
    return ScriptedProvider({
        "planner": plan_json,
        "router": "function", "spec": SPEC, "developer": CODE, "qa": "[]", "doc": DOC,
    })


def _poll(client: TestClient, token: str, until, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    state: dict = {}
    while time.time() < deadline:
        state = client.get(f"/api/plan/{token}").json()
        if until(state):
            return state
        time.sleep(0.05)
    raise AssertionError(f"plan session never reached the awaited phase; last={state}")


def test_plan_proposes_then_human_approves_then_ships(tmp_path):
    plan_json = '{"steps":[{"org":"software","goal":"add two numbers"}]}'
    client = TestClient(create_app(data_dir=tmp_path, provider=_provider(plan_json)))

    token = client.post("/api/plan/start", json={"request": "make me an adder"}).json()["token"]

    # the planner proposes a runnable plan and waits for the human
    reviewing = _poll(client, token, lambda s: s["phase"] == "reviewing")
    assert reviewing["runnable"] is True
    assert [step["org"] for step in reviewing["plan"]] == ["software"]
    assert "runnable" in reviewing["gate"]

    # approve → the chain executes through the software org's real gates
    client.post(f"/api/plan/{token}/review", json={"approved": True})

    done = _poll(client, token, lambda s: s["phase"] == "done")
    assert done["accepted"] is True
    assert len(done["steps"]) == 1
    step = done["steps"][0]
    assert step["org"] == "software" and step["accepted"] is True
    # the step persisted as a normal run (so it also shows up in that studio's history)
    assert any(g["gate"] == "validation" for g in step["run"]["gates"])

    # and the step's run is queryable in the shared runs store
    assert any(r["goal"] == "add two numbers" for r in client.get("/api/runs").json())


def test_plan_refine_then_approve_replans(tmp_path):
    # first plan names a studio that doesn't exist -> not runnable; the human refines; re-plan ships.
    bad = '{"steps":[{"org":"marketing","goal":"x"}]}'
    good = '{"steps":[{"org":"software","goal":"add two numbers"}]}'
    from engine.model import SequencedProvider

    provider = SequencedProvider({
        "planner": [bad, bad, bad, good],  # propose_plan retries up to 3x per round; round 1 stays bad
        "router": ["function"], "spec": [SPEC], "developer": [CODE], "qa": ["[]"], "doc": [DOC],
    })
    client = TestClient(create_app(data_dir=tmp_path, provider=provider))
    token = client.post("/api/plan/start", json={"request": "x"}).json()["token"]

    blocked = _poll(client, token, lambda s: s["phase"] == "reviewing")
    assert blocked["runnable"] is False and "not runnable" in blocked["gate"]

    # refine → re-plan (the 4th scripted planner reply is the good one) → now runnable
    client.post(f"/api/plan/{token}/review", json={"approved": False, "feedback": "use real studios"})
    runnable = _poll(client, token, lambda s: s["phase"] == "reviewing" and s["runnable"])
    assert [step["org"] for step in runnable["plan"]] == ["software"]


def test_plan_marks_grounded_steps_and_passes_their_sources(tmp_path):
    # a research step is flagged needs_sources in the review, and the human's pasted sources reach
    # it as a pinned corpus so its grounding can pass.
    report = json.dumps({"topic": "eagles", "claims": [
        {"text": "Bald eagles fly up to 30 mph",
         "citations": [{"source": "src1", "quote": "fly at speeds of up to 30 mph"}]}]})
    plan_json = '{"steps":[{"org":"research","goal":"how fast are eagles"}]}'
    provider = ScriptedProvider({"planner": plan_json, "researcher": report,
                                 "judge": json.dumps([{"index": 0, "verdict": "SUPPORTED"}])})
    client = TestClient(create_app(data_dir=tmp_path, provider=provider))

    token = client.post("/api/plan/start", json={"request": "an eagle report"}).json()["token"]
    reviewing = _poll(client, token, lambda s: s["phase"] == "reviewing")
    assert reviewing["plan"][0]["needs_sources"] is True  # the UI shows a sources box for this step

    # approve with the corpus the report cites into (becomes src1)
    client.post(f"/api/plan/{token}/review", json={"approved": True,
                "sources": [["Bald eagles can fly at speeds of up to 30 mph."]]})
    done = _poll(client, token, lambda s: s["phase"] == "done")
    assert done["accepted"] is True
    assert done["steps"][0]["org"] == "research" and done["steps"][0]["accepted"] is True


def test_plan_state_unknown_token_is_an_error(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=_provider("{}")))
    assert "error" in client.get("/api/plan/nope").json()
