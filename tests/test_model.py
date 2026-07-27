"""engine/model.py — the HTTP-backed local providers (Ollama, LM Studio).

These are the one seam in the codebase that talks to a real network socket, and
until this test file existed, that seam had zero direct coverage: only its
downstream effects (via ScriptedProvider/SequencedProvider in other tests) were
ever exercised. Covers the happy path plus the ProviderError wrapping added
alongside the production-quality audit — a transport failure or a malformed
response body must surface as one catchable type, not whatever urllib/json
happened to raise.
"""

from __future__ import annotations

import json
import urllib.error
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch

import pytest

from engine.model import LMStudioProvider, OllamaProvider, ProviderError


class _FakeResponse:
    """Just enough of `http.client.HTTPResponse` for `propose()` to work with:
    a context manager whose `.read()` returns the body bytes."""

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
    body = json.dumps(payload).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_FakeResponse(body)):
        yield


@contextmanager
def _urlopen_returns_raw(raw: bytes) -> Iterator[None]:
    with patch("urllib.request.urlopen", return_value=_FakeResponse(raw)):
        yield


@contextmanager
def _urlopen_raises(exc: Exception) -> Iterator[None]:
    with patch("urllib.request.urlopen", side_effect=exc):
        yield


def test_ollama_propose_returns_the_response_field_on_success() -> None:
    provider = OllamaProvider(model="llama3.1:8b")
    with _urlopen_returns({"response": "def add(a, b):\n    return a + b\n"}):
        result = provider.propose(role="developer", prompt="write add()")
    assert "return a + b" in result


def test_ollama_propose_wraps_a_network_failure_as_provider_error() -> None:
    provider = OllamaProvider(model="llama3.1:8b")
    with _urlopen_raises(urllib.error.URLError("connection refused")):
        with pytest.raises(ProviderError) as exc_info:
            provider.propose(role="developer", prompt="write add()")
    assert "Ollama" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, urllib.error.URLError)


def test_ollama_propose_wraps_a_timeout_as_provider_error() -> None:
    provider = OllamaProvider(model="llama3.1:8b")
    with _urlopen_raises(TimeoutError("timed out")):
        with pytest.raises(ProviderError):
            provider.propose(role="developer", prompt="write add()")


def test_ollama_propose_wraps_malformed_json_as_provider_error() -> None:
    provider = OllamaProvider(model="llama3.1:8b")
    with _urlopen_returns_raw(b"not json at all"):
        with pytest.raises(ProviderError):
            provider.propose(role="developer", prompt="write add()")


def test_lmstudio_propose_returns_the_message_content_on_success() -> None:
    provider = LMStudioProvider(model="qwen-coder")
    payload = {"choices": [{"message": {"content": "def add(a, b): return a + b"}}]}
    with _urlopen_returns(payload):
        result = provider.propose(role="developer", prompt="write add()")
    assert "return a + b" in result


def test_lmstudio_propose_wraps_a_network_failure_as_provider_error() -> None:
    provider = LMStudioProvider(model="qwen-coder")
    with _urlopen_raises(urllib.error.URLError("connection refused")):
        with pytest.raises(ProviderError):
            provider.propose(role="developer", prompt="write add()")


def test_lmstudio_propose_wraps_an_unexpected_response_shape_as_provider_error() -> None:
    """A 200 whose body doesn't match the Chat Completions shape (e.g. an error
    payload served with a 200 status) must not leak a raw KeyError/IndexError."""
    provider = LMStudioProvider(model="qwen-coder")
    with _urlopen_returns({"error": "model not loaded"}):
        with pytest.raises(ProviderError):
            provider.propose(role="developer", prompt="write add()")
