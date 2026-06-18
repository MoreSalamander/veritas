"""The model boundary — the provider-agnostic seam that lets Veritas ship.

Every LLM call in the organization goes through one interface:

    propose(role, prompt, system) -> text

Because reliability lives in the deterministic gates and not the model, the model
is swappable by design. Dev/test runs on a local model (Ollama) or a scripted
fake; the shipped product swaps in a cloud API behind this same interface — a
config change, never a rewrite. (README/ROADMAP: the shipping constraint.)
"""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from typing import Any


class ModelProvider(ABC):
    """The one seam. A proposer asks; the provider answers with text."""

    @abstractmethod
    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        raise NotImplementedError


class OllamaProvider(ModelProvider):
    """Local-model backend for development. Talks to Ollama's HTTP API.

    Stdlib-only (urllib) so the engine stays dependency-light. The cloud backend
    is a future sibling of this class behind the same interface."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        host: str = "http://localhost:11434",
        temperature: float = 0.2,
        timeout: float = 120.0,
        think: bool = False,
        num_ctx: int | None = None,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.think = think
        # Reasoning needs context room. Ollama defaults each REQUEST to a small window (~4k)
        # regardless of the model's max — so with thinking ON the <think> block fills it and the
        # answer never arrives (done_reason="length", empty response). Raise it for thinking
        # runs unless told otherwise. (A non-thinking call leaves the model default in place.)
        self.num_ctx = num_ctx if num_ctx is not None else (32768 if think else None)

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        # When think=False (the structured-proposal default) a reasoning model answers directly,
        # which is what we want — the artifact, not the chain-of-thought — and faster. When ON,
        # we keep only `response`; `thinking` is the proposer's private process the gates ignore.
        options: dict[str, Any] = {"temperature": self.temperature}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        body = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "stream": False,
            "think": self.think,
            "options": options,
        }
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = payload.get("response", "")
        return str(text)


class ClaudeProvider(ModelProvider):
    """Cloud backend — the Anthropic API. The product-grade proposer. Reliability still
    comes from the gates; a stronger model just proposes better than a local 8b, which is
    what clears app-scale builds. Model id is one of claude-haiku-4-5 / claude-sonnet-4-6 /
    claude-opus-4-8. Reads ANTHROPIC_API_KEY from the environment."""

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 4096) -> None:
        import anthropic  # lazy: only needed when the cloud is actually used

        self._client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(getattr(block, "text", "") for block in message.content)


class ScriptedProvider(ModelProvider):
    """Deterministic fake for tests: canned responses keyed by role. Lets the whole
    pipeline be exercised offline, with no model running — reliability of the org's
    *plumbing* never depends on a model being up."""

    def __init__(self, by_role: dict[str, str]) -> None:
        self._by_role = by_role

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        if role not in self._by_role:
            raise KeyError(f"ScriptedProvider has no response for role {role!r}")
        return self._by_role[role]


class SequencedProvider(ModelProvider):
    """Like ScriptedProvider, but returns a *queue* of responses per role, popped in
    order. Lets a multi-module build give different answers to the same role across
    successive calls (module 1's contract, then module 2's, ...)."""

    def __init__(self, by_role: dict[str, list[str]]) -> None:
        self._queues = {role: list(responses) for role, responses in by_role.items()}

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        queue = self._queues.get(role)
        if not queue:
            raise KeyError(f"SequencedProvider exhausted or missing for role {role!r}")
        return queue.pop(0)
