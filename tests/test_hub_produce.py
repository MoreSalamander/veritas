"""P25f-in-hub — production create mode end to end through the HTTP control plane.

Start a production, the chain runs (the machine floor), the human approves the cut, it lands
human-approved and the style profile compounds. Offline-deterministic via a scripted cast; the
publish/video bit is exercised when ffmpeg is present, tolerated when it isn't.
"""

from __future__ import annotations

import json
import shutil
import time

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider
from hub.app import create_app

CONCEPT = json.dumps({"title": "Why the Sky is Blue", "logline": "a kid learns why the sky is blue",
                      "audience": "kids", "tone": "warm", "target_seconds": 20,
                      "entities": ["Mia", "the sun", "air molecules"]})
SCRIPT = json.dumps({"scenes": [
    {"heading": "A", "beats": [
        {"narration": "Mia looks up at the wide blue sky and wonders why it is blue.", "entities": ["Mia"]},
        {"narration": "The sun pours its light across the whole town below.", "entities": ["the sun"]}]},
    {"heading": "B", "beats": [
        {"narration": "Tiny air molecules scatter the blue light everywhere.", "entities": ["air molecules"]}]},
]})
STORYBOARD = json.dumps({"shots": [
    {"beat_id": "s1b1", "description": "Mia on the grass", "entities": ["Mia"]},
    {"beat_id": "s1b2", "description": "the sun beaming", "entities": ["the sun"]},
    {"beat_id": "s2b1", "description": "molecules scattering", "entities": ["air molecules"]}]})


def _client(tmp_path) -> TestClient:
    provider = ScriptedProvider(
        {"concept": CONCEPT, "scriptwriter": SCRIPT, "storyboard-artist": STORYBOARD})
    return TestClient(create_app(data_dir=tmp_path, provider=provider))


def _poll(client, token, until, timeout=90.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/produce/{token}").json()
        if until(state):
            return state
        time.sleep(0.15)
    raise AssertionError(f"produce session stalled; last={state}")


def test_produce_review_approve_end_to_end(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/produce/start", json={"brief": "explain why the sky is blue"}).json()["token"]

    reviewing = _poll(client, token, lambda s: s["phase"] == "reviewing")
    # the machine floor passed — every recorded gate verdict is in the trust list
    assert reviewing["trust"] and all(g["passed"] for g in reviewing["trust"])
    if shutil.which("ffmpeg"):  # the cut was rendered and is servable
        assert reviewing["video_url"] and reviewing["video_url"].startswith("/productions/")
        assert client.get(reviewing["video_url"]).status_code == 200

    client.post(f"/api/produce/{token}/review", json={"approved": True})
    done = _poll(client, token, lambda s: s["phase"] == "done")
    assert done["result"]["accepted"] and done["result"]["memory_path"]

    profile = client.get("/api/profile/production").json()
    assert profile["approvals"] == 1 and profile["tone"] == "warm"


def test_request_changes_reruns(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/produce/start", json={"brief": "x"}).json()["token"]
    _poll(client, token, lambda s: s["phase"] == "reviewing")
    client.post(f"/api/produce/{token}/review", json={"approved": False, "feedback": "punchier"})
    again = _poll(client, token, lambda s: s["phase"] == "reviewing" and s["iteration"] >= 2)
    assert again["iteration"] >= 2
