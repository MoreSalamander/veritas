"""P23 — semantic recall: find a past lesson even when the wording differs.

Token overlap misses "invert a sequence" against a lesson about "reversing a list" — no shared
words. An embedder ranks by meaning, so it finds it. Proven deterministically with a topic
embedder (the real nomic-embed comparison is a live demo); the plumbing is what's under test.
"""

from __future__ import annotations

import json
import urllib.error
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from engine.embed import Embedder, OllamaEmbedder, cosine
from engine.memory import MemoryRecord, MemoryStore
from engine.model import ProviderError


class TopicEmbedder(Embedder):
    """Deterministic stand-in: maps text to one of three orthogonal 'topic' axes by keyword, so
    paraphrases of the same topic land on the same vector. (Real embeddings do this by meaning.)"""

    def embed(self, text: str) -> list[float]:
        t = text.lower()
        if any(k in t for k in ("revers", "invert", "backward")):
            return [1.0, 0.0, 0.0]
        if any(k in t for k in ("color", "palette", "theme")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def _seed(store: MemoryStore) -> None:
    store.persist(MemoryRecord(category="lesson", title="reversing a list",
                               body="reversing a list returns its elements backward"))
    store.persist(MemoryRecord(category="lesson", title="color palette",
                               body="choosing a tasteful color palette for a theme"))


def test_cosine():
    assert cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine([1, 0, 0], [0, 1, 0]) == 0.0
    assert cosine([], [1.0]) == 0.0


def test_token_overlap_misses_a_paraphrase(tmp_path):
    store = MemoryStore(tmp_path)  # no embedder -> token overlap
    _seed(store)
    assert store.recall("how do I invert a sequence") == []  # different words -> no overlap


def test_semantic_recall_finds_the_paraphrase(tmp_path):
    store = MemoryStore(tmp_path, embedder=TopicEmbedder())
    _seed(store)
    hits = store.recall("how do I invert a sequence", limit=3)
    assert len(hits) == 1 and "reversing" in hits[0].title  # found by meaning; color excluded


def test_embedder_falls_back_to_tokens_when_it_errors(tmp_path):
    class Broken(Embedder):
        def embed(self, text: str) -> list[float]:
            raise RuntimeError("embedder down")

    store = MemoryStore(tmp_path, embedder=Broken())
    _seed(store)
    # query shares a token ("palette") so token-overlap fallback still finds the color lesson
    hits = store.recall("a nice palette")
    assert any("color palette" in h.title for h in hits)


class _FakeResponse:
    """Minimal stand-in for `http.client.HTTPResponse` — a context manager with `.read()`."""

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


def test_ollama_embedder_returns_the_embedding_field_on_success() -> None:
    embedder = OllamaEmbedder()
    with _urlopen_returns({"embedding": [0.1, 0.2, 0.3]}):
        result = embedder.embed("reverse a list")
    assert result == [0.1, 0.2, 0.3]


def test_ollama_embedder_wraps_a_network_failure_as_provider_error() -> None:
    embedder = OllamaEmbedder()
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        with pytest.raises(ProviderError):
            embedder.embed("reverse a list")


def test_ollama_embedder_wraps_a_malformed_embedding_as_provider_error() -> None:
    """The embedding field is present but contains something that can't be coerced
    to float — e.g. the server returned an error message string instead of numbers."""
    embedder = OllamaEmbedder()
    with _urlopen_returns({"embedding": ["not", "a", "vector"]}):
        with pytest.raises(ProviderError):
            embedder.embed("reverse a list")
