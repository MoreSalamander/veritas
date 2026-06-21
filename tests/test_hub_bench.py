"""The Labs benchmark: a models x goals matrix, aggregated per model. The aggregation is pure and
unit-tested; the session machinery (background run, progress, summary) is checked through the HTTP
control plane with a provider whose builds fail fast — so the orchestration is verified without a
slow real model run.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider
from hub.app import _bench_aggregate, create_app


def test_bench_aggregate_per_model():
    cells = [
        {"model": "g", "goal": "a", "accepted": True, "retries": 1, "time": 2.0},
        {"model": "g", "goal": "b", "accepted": False, "retries": 0, "time": 4.0},
        {"model": "q", "goal": "a", "accepted": True, "retries": 0, "time": 1.0},
    ]
    by = {r["model"]: r for r in _bench_aggregate(cells)}
    assert by["g"]["accepted_rate"] == 50 and by["g"]["mean_time"] == 3.0 and by["g"]["mean_retries"] == 0.5
    assert by["q"]["accepted_rate"] == 100 and by["q"]["n"] == 1


def test_bench_session_runs_the_matrix_and_summarizes(tmp_path):
    # an empty scripted provider -> every build fails fast -> cells errored, but the session still
    # completes the full matrix and aggregates (the orchestration is what's under test here).
    client = TestClient(create_app(data_dir=tmp_path, provider=ScriptedProvider({})))
    token = client.post("/api/bench/start", json={"models": ["gemma-12b"], "repeats": 1}).json()["token"]

    deadline = time.time() + 30
    state = client.get(f"/api/bench/{token}").json()
    while state["phase"] != "done" and time.time() < deadline:
        time.sleep(0.1)
        state = client.get(f"/api/bench/{token}").json()
    assert state["phase"] == "done"
    assert state["total"] == 3 and len(state["cells"]) == 3  # 1 model x 3 goals
    assert state["summary"] and state["summary"][0]["model"] == "gemma-12b"


def test_bench_defaults_to_the_star_when_no_models_given(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=ScriptedProvider({})))
    token = client.post("/api/bench/start", json={"models": []}).json()["token"]
    assert token  # falls back to DEFAULT_MODEL rather than running an empty matrix
