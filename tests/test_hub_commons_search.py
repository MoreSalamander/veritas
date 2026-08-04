"""POST /api/commons/search (P28c): the live-web-search entry into the Knowledge Graph, over the
HTTP control plane. A ScriptedSearchClient is injected throughout — this suite proves the Hub's own
plumbing and the machine-fetched containment, not Parallel's real API (that's covered live by a
manual smoke test and offline by tests/test_parallel_client.py's request/response contract tests).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.memory import TRUST_MACHINE_FETCHED, TRUST_VOUCHED
from engine.model import ScriptedProvider
from hub.app import create_app
from hub.parallel_client import ExtractResult, ParallelClient, ScriptedSearchClient, SearchResult


def _client(tmp_path, search_client=None):
    return TestClient(create_app(
        data_dir=tmp_path, provider=ScriptedProvider({}), search_client=search_client,
    ))


def test_search_ingests_and_lists_a_machine_fetched_source(tmp_path):
    search_client = ScriptedSearchClient(
        search_by_query={"ls bellhousing pattern": [SearchResult(url="https://x.com", title="X")]},
        extract_by_url={"https://x.com": ExtractResult(
            url="https://x.com", title="X", content="the LS pattern differs from SBC",
        )},
    )
    client = _client(tmp_path, search_client)

    resp = client.post("/api/commons/search", json={"query": "ls bellhousing pattern"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "ls bellhousing pattern"
    assert len(body["added"]) == 1
    assert body["added"][0]["url"] == "https://x.com"

    listed = client.get("/api/commons").json()
    assert len(listed) == 1
    assert TRUST_MACHINE_FETCHED in listed[0]["tags"]
    assert TRUST_VOUCHED not in listed[0]["tags"]
    assert "differs from SBC" in listed[0]["body"]


def test_search_with_nothing_findable_returns_an_empty_added_list(tmp_path):
    client = _client(tmp_path, ScriptedSearchClient())
    resp = client.post("/api/commons/search", json={"query": "nothing findable"})
    assert resp.status_code == 200
    assert resp.json()["added"] == []
    assert client.get("/api/commons").json() == []


def test_search_with_a_blank_query_is_a_400(tmp_path):
    client = _client(tmp_path, ScriptedSearchClient())
    resp = client.post("/api/commons/search", json={"query": "   "})
    assert resp.status_code == 400


def test_search_without_an_api_key_is_a_503(tmp_path, monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    # No search_client injected -> create_app falls back to a real ParallelClient(), which must
    # be gated on .available() before ever attempting a live call.
    client = TestClient(create_app(data_dir=tmp_path, provider=ScriptedProvider({})))
    resp = client.post("/api/commons/search", json={"query": "anything"})
    assert resp.status_code == 503
