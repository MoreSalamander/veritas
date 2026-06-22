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

from engine.run import Phase, emit_activity


def _announce(role: str) -> None:
    """Light this proposer's box in the live trace — every LLM call announces who's working, so the
    Hub lights the right cast box regardless of org. Purely observational (a no-op if nobody's
    watching)."""
    emit_activity(Phase.SYNTHESIZE, role, "working…")


class ModelProvider(ABC):
    """The one seam. A proposer asks; the provider answers with text."""

    @abstractmethod
    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        raise NotImplementedError

    def for_shape(self, shape: str) -> "ModelProvider":
        """Return a provider tuned for a build of this shape ("function" | "module" | "app").
        Default: unchanged. Local reasoning models override this to turn THINKING on for harder
        shapes — a clean, measured win (see OllamaProvider.for_shape)."""
        return self

    def retry_budget(self, default: int = 3) -> int:
        """How many attempts the retry loop should allow. Default: the standard 3. A reasoning
        model running with THINKING on overrides this DOWN — a careful think-then-answer that
        fails twice rarely flips on a third, and each thinking retry is the most expensive op in
        the system. Capping bounds worst-case latency (one bench codec build spiraled to 1191s /
        4 retries) WITHOUT lowering accept-rate (a doomed build fails either way, just sooner)."""
        return default


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
        num_predict: int | None = None,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.think = think
        # Reasoning is unbounded and needs TWO things, or it returns an empty answer
        # (done_reason="length") — verified the hard way with Qwen3.5:
        #   num_ctx     — room to hold the prompt + the whole <think> block + the answer.
        #   num_predict — generation budget; Ollama caps each request (~4k by default), and a
        #                 long <think> burns it before the answer is ever emitted.
        # We raise both for thinking runs unless told otherwise; non-thinking calls leave the
        # model defaults in place (a direct answer is short and fast).
        self.num_ctx = num_ctx if num_ctx is not None else (16384 if think else None)
        self.num_predict = num_predict if num_predict is not None else (8192 if think else None)

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        _announce(role)
        # When think=False (the structured-proposal default) a reasoning model answers directly,
        # which is what we want — the artifact, not the chain-of-thought — and faster. When ON,
        # we keep only `response`; `thinking` is the proposer's private process the gates ignore.
        options: dict[str, Any] = {"temperature": self.temperature}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
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

    def for_shape(self, shape: str) -> "ModelProvider":
        # Adaptive thinking, earned by the benchmark: on the local star (gemma4:12b), turning
        # THINKING on flips MODULE builds from never-ships to first-try-green (temp 0/2 -> 2/2,
        # codec 0/2 -> 1/2), while on FUNCTIONS it's just ~10x slower for no gain (and failed a
        # function think-off clears). So: think for module/app, direct for function. A reasoning
        # model that isn't a thinker simply ignores the flag, so this is safe for every local model.
        want_think = shape in ("module", "app")
        if want_think == self.think:
            return self
        return OllamaProvider(
            model=self.model, host=self.host, temperature=self.temperature,
            timeout=600.0 if want_think else 120.0, think=want_think,
        )

    def retry_budget(self, default: int = 3) -> int:
        # Thinking already does the reasoning up front; a 3rd expensive thinking retry rarely
        # converts a fail, so cap to 2 when thinking. Off-thinking keeps the full budget (those
        # retries are cheap AND genuinely useful — the involution/clamp self-corrections).
        return 2 if self.think else default


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
        _announce(role)
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
        _announce(role)
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
        _announce(role)
        queue = self._queues.get(role)
        if not queue:
            raise KeyError(f"SequencedProvider exhausted or missing for role {role!r}")
        return queue.pop(0)
