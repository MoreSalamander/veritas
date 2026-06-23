"""Knowledge mode through the hub — answer from the model's own knowledge, flagged honestly.

Offline with a SequencedProvider so the brief is deterministic: a decomposition call, then assess
calls per sub-question. Confirms the endpoint returns confident vs flagged claims and the disclosed
confident-wrong rate — and that NOTHING is presented as verified.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from engine.model import SequencedProvider
from hub.app import create_app


def _poll(client: TestClient, token: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    state: dict = {}
    while time.time() < deadline:
        state = client.get(f"/api/brief/{token}").json()
        if state.get("done") or state.get("error"):
            return state
        time.sleep(0.05)
    raise AssertionError(f"brief never finished; last={state}")


def test_brief_returns_confident_and_flagged_claims(tmp_path):
    provider = SequencedProvider({
        "knowledge-writer": ["Where is the band from?\nWho are the members?"],
        # 5 samples x 2 sub-questions: Q1 consistent (confident), Q2 scattered (flagged)
        "knowledge": ["london", "london", "london", "london", "london",
                      "a b", "c d", "e f", "g h", "a b"],
    })
    client = TestClient(create_app(data_dir=tmp_path, provider=provider))

    token = client.post("/api/brief/start", json={"question": "tell me about the band"}).json()["token"]
    state = _poll(client, token)
    brief = state["brief"]

    assert brief["confident"] == 1 and brief["flagged"] == 1
    assert brief["confident_wrong_rate"]  # the honest disclosure is present
    levels = {c["question"]: c["level"] for c in brief["claims"]}
    assert levels["Where is the band from?"] == "confident"
    assert levels["Who are the members?"] == "flagged"
    # nothing claims to be verified — the confident claim's reason says so
    conf = next(c for c in brief["claims"] if c["level"] == "confident")
    assert "unverified" in conf["reason"]


def test_brief_unknown_token_is_an_error(tmp_path):
    provider = SequencedProvider({"knowledge-writer": [""], "knowledge": ["x"]})
    client = TestClient(create_app(data_dir=tmp_path, provider=provider))
    assert "error" in client.get("/api/brief/nope").json()
