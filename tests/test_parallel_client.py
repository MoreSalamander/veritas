"""hub/parallel_client.py — offline, deterministic. ParallelClient's HTTP transport is exercised
by mocking urllib.request.urlopen (same pattern test_model.py uses for OllamaProvider); the
pipeline-facing tests elsewhere in the suite use ScriptedSearchClient and never touch this at all.
"""

from __future__ import annotations

import json
import urllib.error
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from commons.parallel_client import (
    ExtractResult,
    ParallelClient,
    ParallelUnavailable,
    ScriptedSearchClient,
    SearchResult,
)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


@contextmanager
def _urlopen_returns(payload: dict[str, Any]) -> Iterator[None]:
    with patch("urllib.request.urlopen", return_value=_FakeResponse(json.dumps(payload).encode())):
        yield


@contextmanager
def _urlopen_raises(exc: Exception) -> Iterator[None]:
    with patch("urllib.request.urlopen", side_effect=exc):
        yield


# --- ParallelClient.available() -----------------------------------------------------------

def test_available_reflects_the_env_var(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    assert ParallelClient.available() is False
    monkeypatch.setenv("PARALLEL_API_KEY", "k")
    assert ParallelClient.available() is True


def test_search_without_a_key_fails_honestly(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    client = ParallelClient(api_key="")
    with pytest.raises(ParallelUnavailable, match="not set"):
        client.search("anything")


# --- search() ----------------------------------------------------------------------------

def test_search_parses_results():
    client = ParallelClient(api_key="k")
    with _urlopen_returns({
        "results": [
            {"url": "https://x.com/a", "title": "A", "publish_date": "2026-01-01",
             "excerpts": ["snippet one"]},
        ],
    }):
        results = client.search("ls bellhousing pattern")
    assert results == [SearchResult(
        url="https://x.com/a", title="A", publish_date="2026-01-01", excerpts=["snippet one"],
    )]


def test_search_with_no_results_returns_an_empty_list_not_an_error():
    client = ParallelClient(api_key="k")
    with _urlopen_returns({"results": []}):
        assert client.search("nothing findable") == []


def test_search_wraps_a_network_failure():
    client = ParallelClient(api_key="k")
    with _urlopen_raises(urllib.error.URLError("refused")):
        with pytest.raises(ParallelUnavailable):
            client.search("x")


# --- extract() ---------------------------------------------------------------------------

def test_extract_returns_joined_excerpts():
    # Verified live against the real API: there is no `full_content` field (a request that sends
    # one is rejected outright) — `excerpts` is what's actually returned.
    client = ParallelClient(api_key="k")
    with _urlopen_returns({"results": [
        {"url": "https://x.com/a", "title": "A", "publish_date": None, "excerpts": ["e1", "e2"]},
    ]}):
        got = client.extract("https://x.com/a")
    assert got == ExtractResult(
        url="https://x.com/a", title="A", publish_date=None, content="e1\n\ne2",
    )


def test_extract_with_no_results_and_no_errors_fails_honestly():
    client = ParallelClient(api_key="k")
    with _urlopen_returns({"results": [], "errors": []}):
        with pytest.raises(ParallelUnavailable, match="no extraction"):
            client.extract("https://x.com/dead")


def test_extract_surfaces_a_per_url_error_from_the_api():
    # A real, observed shape: a blocked/403'd URL lands in `errors`, not silently absent from
    # `results` — the failure reason should reach the caller, not collapse to a generic message.
    client = ParallelClient(api_key="k")
    with _urlopen_returns({"results": [], "errors": [
        {"url": "https://x.com/a", "error_type": "http_error", "http_status_code": 403},
    ]}):
        with pytest.raises(ParallelUnavailable, match="403"):
            client.extract("https://x.com/a")


def test_extract_with_empty_excerpts_falls_through_to_the_errors_check():
    # A result present but with nothing usable in it must never become a persisted record with an
    # empty body — same "fail honestly" discipline as TranscriptUnavailable.
    client = ParallelClient(api_key="k")
    with _urlopen_returns({"results": [{"url": "https://x.com/a", "excerpts": []}], "errors": []}):
        with pytest.raises(ParallelUnavailable, match="no extraction"):
            client.extract("https://x.com/a")


# --- ScriptedSearchClient ------------------------------------------------------------------

def test_scripted_client_search_is_unscripted_safe():
    client = ScriptedSearchClient()
    assert client.search("anything") == []


def test_scripted_client_extract_raises_for_an_unscripted_url():
    client = ScriptedSearchClient()
    with pytest.raises(ParallelUnavailable):
        client.extract("https://unknown.example")


def test_scripted_client_returns_canned_results():
    result = SearchResult(url="https://x.com", title="X", excerpts=["e"])
    extracted = ExtractResult(url="https://x.com", title="X", content="full page")
    client = ScriptedSearchClient(
        search_by_query={"q": [result]}, extract_by_url={"https://x.com": extracted},
    )
    assert client.search("q") == [result]
    assert client.extract("https://x.com") == extracted
