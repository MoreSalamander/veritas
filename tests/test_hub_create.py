"""P24 — create mode runs end to end through the hub.

The interview (model proposes a gateable spec), the build (manufactured hard gates pass on a real
render), the three-tier trust report, the human Approve, and the human-approved memory record — all
driven over the HTTP control plane, with a scripted provider so it's offline and deterministic. The
engine functions (`interview`, `build_create_page`) are unchanged; the hub just turns their blocking
callbacks into a turn-based web conversation.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider
from hub.app import create_app

SPEC = {
    "title": "Landing", "description": "a landing page",
    "required_elements": ["nav", "h1", "button"],
    "aesthetics": {"theme": "dark", "min_contrast": 4.5,
                   "fonts": ["monospace"], "palette": ["#0a0a0a", "#ffffff"]},
}
GOOD = ("<!doctype html><html><head><style>"
        "body{background:#0a0a0a;color:#ffffff;font-family:monospace;}"
        "a,button{color:#ffffff;background:#0a0a0a;font-family:monospace;}"
        "</style></head><body><nav><a href='#'>Home</a></nav><h1>Hi</h1><button>Go</button></body></html>")


def _provider() -> ScriptedProvider:
    # interviewer returns a complete gateable spec immediately (no questions); the developer
    # returns a page that clears every manufactured hard gate.
    return ScriptedProvider({"interviewer": json.dumps({"spec": SPEC}), "web-developer": GOOD})


def _poll(client: TestClient, token: str, until, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/create/{token}").json()
        if until(state):
            return state
        time.sleep(0.1)
    raise AssertionError(f"create session never reached the awaited phase; last={state}")


def test_create_mode_end_to_end_human_approved(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=_provider()))

    token = client.post("/api/create/start", json={"goal": "a landing page"}).json()["token"]

    # the manufactured hard gates run on a real render, then it waits for the human
    reviewing = _poll(client, token, lambda s: s["phase"] == "reviewing")
    trust = reviewing["trust"]
    names = {g["name"] for g in trust["machine"]}
    assert {"render", "structure", "theme", "contrast", "fonts", "palette"} <= names
    assert all(g["passed"] for g in trust["machine"])  # machine-proven floor cleared
    assert trust["model"] == []                         # no model-judge tier in create mode
    assert trust["human"] == "pending"                  # awaiting the human gate
    assert reviewing["spec"]["title"] == "Landing"

    # the human is the gate: approve → ships human-approved
    client.post(f"/api/create/{token}/review", json={"approved": True})
    done = _poll(client, token, lambda s: s["phase"] == "done")
    assert done["result"]["accepted"]
    assert done["result"]["memory_path"]  # remembered

    # the approval taught the aesthetic profile (the loop compounds)
    profile = client.get("/api/profile/web").json()
    assert profile["approvals"] == 1
    assert profile["theme"] == "dark"


def test_create_mode_request_changes_then_done(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=_provider()))
    token = client.post("/api/create/start", json={"goal": "a landing page"}).json()["token"]

    _poll(client, token, lambda s: s["phase"] == "reviewing")
    # request changes once (no approval) → re-proposes, comes back to review at a later iteration
    client.post(f"/api/create/{token}/review", json={"approved": False, "feedback": "more air"})
    again = _poll(client, token, lambda s: s["phase"] == "reviewing" and s["iteration"] >= 2)
    assert again["iteration"] >= 2
