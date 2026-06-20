"""The Hub serves Mission Control, runs, and memory from REAL engine data.

Driven offline with a ScriptedProvider, so no model is needed — the API exercises
the real pipeline, run persistence, and memory, end to end. A hub software run also
documents the function (the doc role), so its examples are verified to run too.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider
from hub.app import create_app

GOOD_SPEC = json.dumps(
    {
        "function_name": "add",
        "description": "add two numbers",
        "signature": "def add(a, b)",
        "cases": [{"args": [1, 2], "expected": 3}, {"args": [4, 4], "expected": 8}],
    }
)
GOOD_CODE = "def add(a, b):\n    return a + b\n"
GOOD_DOC = "# add\n\nAdds two numbers.\n\n```python\nassert add(2, 3) == 5\nprint(add(10, 20))\n```\n"


def _client(tmp_path):
    provider = ScriptedProvider(
        {"spec": GOOD_SPEC, "developer": GOOD_CODE, "qa": "[]", "doc": GOOD_DOC}
    )
    return TestClient(create_app(data_dir=tmp_path, provider=provider))


def test_post_run_executes_real_pipeline_and_persists(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/runs", json={"goal": "add two numbers"})
    assert resp.status_code == 200
    run = resp.json()
    assert run["accepted"] is True
    gate_names = [g["gate"] for g in run["gates"]]
    assert "validation" in gate_names  # the full cast really ran
    assert "examples-run" in gate_names  # the doc role ran and its examples executed
    types = {a["type"] for a in run["artifacts"]}
    assert {"spec", "code", "documentation"} <= types


def test_runs_and_dashboard_reflect_real_state(tmp_path):
    client = _client(tmp_path)
    client.post("/api/runs", json={"goal": "add two numbers"})

    runs = client.get("/api/runs").json()
    assert len(runs) == 1

    dash = client.get("/api/dashboard").json()
    assert dash["total_runs"] == 1
    assert dash["success_rate"] == 100.0
    assert dash["memory_entries"] >= 3  # spec + code + documentation persisted


def test_memory_endpoint_lists_records(tmp_path):
    client = _client(tmp_path)
    client.post("/api/runs", json={"goal": "add two numbers"})
    mem = client.get("/api/memory").json()
    assert any(m["category"] == "artifact" for m in mem)


def test_index_is_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "VERI" in resp.text


def test_orgs_endpoint_lists_registry(tmp_path):
    client = _client(tmp_path)
    orgs = client.get("/api/orgs").json()
    assert {o["name"] for o in orgs} == {"software", "web", "research", "production", "empirical",
                                         "newsroom", "education", "startup", "game"}
    assert all(o["input_noun"] and o["produces"] and o["verified_by"] for o in orgs)


def test_start_run_streams_real_activity_then_completes(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/runs/start", json={"goal": "add two numbers"}).json()["token"]

    state = None
    for _ in range(200):  # the offline build finishes in well under this
        state = client.get(f"/api/runs/progress/{token}").json()
        if state.get("done"):
            break
        time.sleep(0.05)

    assert state is not None and state["done"] and state["error"] is None
    assert state["run"] is not None and state["run"]["accepted"]
    # the timeline carried REAL gate verdicts and the persist step — not a script
    phases = {e["phase"] for e in state["events"]}
    assert {"verify", "persist"} <= phases
    assert "validation" in [e["actor"] for e in state["events"]]
    # and the finished run landed in the persisted list
    assert len(client.get("/api/runs").json()) == 1


def test_progress_for_unknown_token_is_an_error(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/runs/progress/does-not-exist").json()["error"]


# --- the second org (Web Studio) is a first-class citizen of the hub ---

WEB_SPEC = json.dumps(
    {"title": "Landing", "description": "a landing page", "required_elements": ["nav", "h1", "button"]}
)
WEB_PAGE = (
    "<!doctype html><html><head><title>Landing</title></head><body>"
    "<nav><a href='#'>Home</a></nav><h1>Welcome</h1><button>Go</button></body></html>"
)


def test_web_org_registered_with_an_all_hard_roster(tmp_path):
    client = _client(tmp_path)
    assert {o["name"] for o in client.get("/api/orgs").json()} >= {"software", "web"}
    roster = client.get("/api/orgs/web/roster").json()
    names = {g["name"] for g in roster["gates"]}
    assert {"render", "layout", "structure", "a11y"} <= names
    assert all(g["determinism"] == "hard" for g in roster["gates"])  # no soft gates yet


def test_web_run_through_the_hub_renders_and_ships(tmp_path):
    provider = ScriptedProvider({"designer": WEB_SPEC, "web-developer": WEB_PAGE})
    client = TestClient(create_app(data_dir=tmp_path, provider=provider))
    run = client.post("/api/runs", json={"goal": "a landing page", "org": "web"}).json()
    assert run["accepted"] is True and run["org"] == "web"
    gate_names = [g["gate"] for g in run["gates"]]
    assert "render" in gate_names and "validation" in gate_names
    # the two orgs keep separate institutional memory
    assert (tmp_path / "memory" / "web" / "institutional").exists()


# --- the third org (Research Studio): grounded over sources passed through the hub ---

RESEARCH_REPORT = json.dumps({
    "topic": "eagles",
    "claims": [{"text": "Bald eagles fly up to 30 mph",
                "citations": [{"source": "src1", "quote": "fly at speeds of up to 30 mph"}]}],
})


def test_research_org_registered_and_needs_sources(tmp_path):
    client = _client(tmp_path)
    orgs = {o["name"]: o for o in client.get("/api/orgs").json()}
    assert "research" in orgs and orgs["research"]["needs_sources"] is True
    assert orgs["software"]["needs_sources"] is False
    roster = client.get("/api/orgs/research/roster").json()
    assert {"citations-resolve", "quotes-verbatim", "support"} <= {g["name"] for g in roster["gates"]}


def test_research_run_through_the_hub_grounds_over_sources(tmp_path):
    provider = ScriptedProvider({"researcher": RESEARCH_REPORT,
                                 "judge": json.dumps([{"index": 0, "verdict": "SUPPORTED"}])})
    client = TestClient(create_app(data_dir=tmp_path, provider=provider))
    run = client.post("/api/runs", json={
        "goal": "how fast do bald eagles fly", "org": "research",
        "sources": ["Bald eagles can fly at speeds of up to 30 mph and dive at over 100 mph."],
    }).json()
    assert run["accepted"] is True and run["org"] == "research"
    gate_names = [g["gate"] for g in run["gates"]]
    assert "quotes-verbatim" in gate_names and "validation" in gate_names
    assert (tmp_path / "memory" / "research" / "institutional").exists()


def test_software_run_uses_isolated_memory_namespace(tmp_path):
    client = _client(tmp_path)
    sw = client.post("/api/runs", json={"goal": "add two numbers", "org": "software"}).json()
    assert sw["org"] == "software" and sw["accepted"]

    # Per-org memory namespace on disk (the tenant-isolation shape).
    assert (tmp_path / "memory" / "software" / "institutional").exists()

    mem = client.get("/api/memory").json()
    assert {m["org"] for m in mem} == {"software"}

    dash = client.get("/api/dashboard").json()
    assert dash["total_runs"] == 1
    assert dash["by_org"]["software"] == 1 and dash["by_org"].get("web", 0) == 0
