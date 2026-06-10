"""The Hub serves Mission Control, runs, and memory from REAL engine data.

Driven offline with a ScriptedProvider, so no model is needed — the API exercises
the real pipeline, run persistence, and memory, end to end. A hub software run also
documents the function (the doc role), so its examples are verified to run too.
"""

from __future__ import annotations

import json

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
    assert {o["name"] for o in orgs} == {"software"}
    assert all(o["input_noun"] and o["produces"] and o["verified_by"] for o in orgs)


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
    assert dash["by_org"] == {"software": 1}
