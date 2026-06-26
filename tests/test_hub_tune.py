"""Prompt Studio through the hub — A/B a candidate Spec prompt, verdict decided by accept-rate.

Offline: a prompt-sensitive provider emits a usable spec only when the Spec prompt carries a marker,
so a function build's fate is a clean function of the prompt. The live baseline lacks the marker; a
candidate carrying it wins the A/B — and the hub reports it as improved, with per-variant accept-rates.
Nothing inspects the wording; the gates decide.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from engine.model import ModelProvider
from hub.app import create_app

MARKER = "GOLDEN"
GOOD_SPEC = json.dumps(
    {"function_name": "f", "description": "d", "signature": "def f(a, b)",
     "cases": [{"args": [1, 2], "expected": 3}]}
)


class _SpecMarkerProvider(ModelProvider):
    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        if role == "router":
            return "function"
        if role == "spec":
            return GOOD_SPEC if system and MARKER in system else "just prose, not a spec"
        if role == "developer":
            return "def f(a, b):\n    return a + b\n"
        if role == "qa":
            return "[]"
        if role == "doc":
            return "# f\n\n```python\nassert f(1, 2) == 3\n```\n"
        return ""


def _poll(client: TestClient, token: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    state: dict = {}
    while time.time() < deadline:
        state = client.get(f"/api/tune/{token}").json()
        if state.get("phase") == "done" or state.get("error"):
            return state
        time.sleep(0.05)
    raise AssertionError(f"tune never finished; last={state}")


def test_a_marked_candidate_beats_the_unmarked_live_prompt(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=_SpecMarkerProvider()))
    candidate = f"You are a spec writer. {MARKER}. Return the schema."  # carries the marker
    token = client.post("/api/tune/start", json={"candidate": candidate, "repeats": 1}).json()["token"]
    state = _poll(client, token)

    v = state["verdict"]
    assert v["candidate_rate"] == 100 and v["baseline_rate"] == 0  # gates, not wording, decide
    assert v["improved"] and v["winner"] == "candidate" and v["delta"] == 100


def test_empty_candidate_is_refused(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=_SpecMarkerProvider()))
    assert client.post("/api/tune/start", json={"candidate": "   "}).status_code == 400


def test_baseline_endpoint_returns_the_live_prompt(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=_SpecMarkerProvider()))
    prompt = client.get("/api/tune/baseline").json()["prompt"]
    assert "specification" in prompt.lower()  # it's the real SPEC_SYSTEM


def test_unknown_tune_token_is_an_error(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=_SpecMarkerProvider()))
    assert "error" in client.get("/api/tune/nope").json()
