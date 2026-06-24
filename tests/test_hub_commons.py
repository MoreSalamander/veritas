"""The Second Brain endpoints (P28a): manual source entry + listing, over the HTTP control plane.

Containment is enforced end to end — a source with no origin is refused with a 400, not silently
dropped — and a saved source comes back through the list endpoint carrying its human-vouched tag.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider
from hub.app import create_app
from hub.ingest import FetchedTranscript, ScriptedFetcher


def _client(tmp_path, fetcher=None):
    return TestClient(
        create_app(data_dir=tmp_path, provider=ScriptedProvider({}), fetcher=fetcher)
    )


def test_save_then_list_a_curated_source(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/commons",
        json={
            "url": "https://youtu.be/abc123",
            "channel": "Some Lecturer",
            "transcript": "A talk about encode/decode round trips.",
            "captured_why": "for the research org",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["trust"] == "human-vouched"

    listed = client.get("/api/commons").json()
    assert len(listed) == 1
    assert listed[0]["url"] == "https://youtu.be/abc123"
    assert listed[0]["captured_why"] == "for the research org"
    assert "human-vouched" in listed[0]["tags"]


def test_source_without_origin_is_refused_with_400(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/commons", json={"url": "", "transcript": "orphaned"})
    assert resp.status_code == 400
    assert client.get("/api/commons").json() == []


def test_paste_url_fetches_the_transcript(tmp_path):
    # P28b: no transcript pasted -> the fetcher recovers it from the URL; title/channel fill in.
    fetcher = ScriptedFetcher(
        {
            "https://youtu.be/vid42": FetchedTranscript(
                text="The fetched spoken words go here.",
                title="A Real Talk",
                channel="Conference Org",
            )
        }
    )
    client = _client(tmp_path, fetcher=fetcher)
    resp = client.post(
        "/api/commons", json={"url": "https://youtu.be/vid42", "captured_why": "relevant"}
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "A Real Talk"

    listed = client.get("/api/commons").json()
    assert listed[0]["body"] == "The fetched spoken words go here."
    assert listed[0]["channel"] == "Conference Org"
    assert "human-vouched" in listed[0]["tags"]


def test_full_transcript_has_its_own_page(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/api/commons",
        json={"url": "https://youtu.be/abc123", "transcript": "the entire transcript body"},
    )
    rec_id = client.get("/api/commons").json()[0]["id"]
    page = client.get(f"/commons/{rec_id}")
    assert page.status_code == 200
    assert "the entire transcript body" in page.text
    assert "human-vouched" in page.text
    assert client.get("/commons/mem_nope").status_code == 404


def test_url_with_no_transcript_fails_honestly(tmp_path):
    # An unknown URL has no scripted transcript -> 422, and nothing junk is persisted.
    client = _client(tmp_path, fetcher=ScriptedFetcher({}))
    resp = client.post("/api/commons", json={"url": "https://youtu.be/nocaps"})
    assert resp.status_code == 422
    assert client.get("/api/commons").json() == []
