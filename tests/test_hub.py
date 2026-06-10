"""The Hub serves Mission Control, runs, and memory from REAL engine data.

Driven offline with a ScriptedProvider, so no model is needed — the API exercises
the real pipeline, run persistence, and memory, end to end.
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


def _client(tmp_path):
    provider = ScriptedProvider({"spec": GOOD_SPEC, "developer": GOOD_CODE, "qa": "[]"})
    return TestClient(create_app(data_dir=tmp_path, provider=provider))


def test_post_run_executes_real_pipeline_and_persists(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/runs", json={"goal": "add two numbers"})
    assert resp.status_code == 200
    run = resp.json()
    assert run["accepted"] is True
    gate_names = [g["gate"] for g in run["gates"]]
    assert "validation" in gate_names  # the full cast really ran
    assert any(a["store"] == "institutional" for a in run["artifacts"])


def test_runs_and_dashboard_reflect_real_state(tmp_path):
    client = _client(tmp_path)
    client.post("/api/runs", json={"goal": "add two numbers"})

    runs = client.get("/api/runs").json()
    assert len(runs) == 1

    dash = client.get("/api/dashboard").json()
    assert dash["total_runs"] == 1
    assert dash["success_rate"] == 100.0
    assert dash["memory_entries"] >= 2  # spec + code persisted


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
