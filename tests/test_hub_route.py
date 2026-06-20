"""The Home front door's router: a request -> a proposed studio + goal (the model proposes, the
user confirms). A scripted model routes by its JSON; an absent/failed model falls back to keywords.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider
from hub.app import create_app


def _client(router_json: str | None) -> TestClient:
    by_role = {"router": router_json} if router_json else {}
    return TestClient(create_app(data_dir=Path(tempfile.mkdtemp()), provider=ScriptedProvider(by_role)))


def test_model_route_is_used_when_valid():
    c = _client('{"org": "production", "goal": "a 30s video on the sky"}')
    r = c.post("/api/route", json={"request": "make me a video about the sky"}).json()
    assert r["org"] == "production" and r["goal"] == "a 30s video on the sky"
    assert r["title"] and r["produces"]


def test_keyword_fallback_when_model_unavailable():
    c = _client(None)  # no 'router' response -> propose raises -> keyword fallback
    assert c.post("/api/route", json={"request": "a short animated film"}).json()["org"] == "production"
    assert c.post("/api/route", json={"request": "a landing page for a cafe"}).json()["org"] == "web"
    assert c.post("/api/route", json={"request": "does an ensemble outperform one model"}).json()["org"] == "empirical"
    assert c.post("/api/route", json={"request": "a teaching lesson on photosynthesis"}).json()["org"] == "education"


def test_invalid_model_org_falls_back_to_keywords():
    c = _client('{"org": "not-a-real-org", "goal": "x"}')
    assert c.post("/api/route", json={"request": "a function that sorts a list"}).json()["org"] == "software"
