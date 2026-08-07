"""The model catalog — which models can propose, and what each one clears.

Engine knowledge extracted from the old hub layer: the catalog, the measured
capability notes, and the provider constructors (including the context-window
sizing that was measured against real failures). Reliability comes from the
gates regardless of which model proposes — the catalog just lets a caller
discover which model a build needs.
"""

from __future__ import annotations

import os
from typing import TypedDict

from engine.model import ClaudeProvider, ModelProvider, OllamaProvider


# The model toggle: local Ollama models (free) plus the three Claude tiers. Each entry
# declares its kind ("ollama" | "claude"), the exact id, and whether to run with
# reasoning ON. `think` pairs with context: qwen3.5:9b runs think-off (fast, direct);
# qwen3.5-64k has the context headroom to reason AND still answer, so it runs think-on.
class ModelSpec(TypedDict):
    label: str
    cost: str
    kind: str  # "ollama" | "claude"
    id: str
    think: bool


MODELS: dict[str, ModelSpec] = {
    "gemma-12b": {"label": "Gemma 12B · local ★", "cost": "free", "kind": "ollama", "id": "gemma4:12b", "think": False},
    "qwen": {"label": "Qwen3.5 9B · local", "cost": "free", "kind": "ollama", "id": "qwen3.5:9b", "think": False},
    "qwen-64k": {"label": "Qwen3.5 64k · local · thinking", "cost": "free", "kind": "ollama", "id": "qwen3.5-64k:latest", "think": True},
    "llama": {"label": "Llama3.1 8B · local", "cost": "free", "kind": "ollama", "id": "llama3.1:8b", "think": False},
    "haiku": {"label": "Claude Haiku", "cost": "~1–3¢/build", "kind": "claude", "id": "claude-haiku-4-5", "think": False},
    "sonnet": {"label": "Claude Sonnet", "cost": "~4–8¢/build", "kind": "claude", "id": "claude-sonnet-4-6", "think": False},
    "opus": {"label": "Claude Opus", "cost": "~6–13¢/build", "kind": "claude", "id": "claude-opus-4-8", "think": False},
}

DEFAULT_MODEL = os.environ.get("VERITAS_MODEL", "gemma-12b")  # hosted (Claude-only) sets e.g. "sonnet"

# Honest, measured capability notes — what each model reliably CLEARS, from the project's own
# benchmark runs. (Milestone 5 wires these to live bench results; until then they're the findings.)
MODEL_NOTES: dict[str, str] = {
    "gemma-12b": "Clears function + production chains. The local star.",
    "qwen": "Fast, but drifts on grounding — good for simple functions, not video.",
    "qwen-64k": "Thinking model — better first-try on hard goals, ~7x slower.",
    "llama": "Older 8B — basic functions only; weakest of the locals.",
    "haiku": "Cloud, cheap — clears more than the locals.",
    "sonnet": "Cloud — clears module/app scale where local models can't.",
    "opus": "Cloud — strongest; for the hardest builds.",
}


# The operator's runtime toggle (the developer cloud switch on the local
# face): when set, requests that rode the import-time default get the
# override instead. An EXPLICIT model choice always wins — the toggle moves
# the default, never overrules a person. None means the toggle is off.
_DEFAULT_OVERRIDE: str | None = None


def set_default_override(model: str | None) -> None:
    global _DEFAULT_OVERRIDE
    if model is not None and model not in MODELS:
        raise ValueError(f"unknown model {model!r}")
    _DEFAULT_OVERRIDE = model


def get_default_override() -> str | None:
    return _DEFAULT_OVERRIDE


def provider_for(model: str) -> ModelProvider:
    if model == DEFAULT_MODEL and _DEFAULT_OVERRIDE:
        model = _DEFAULT_OVERRIDE
    spec = MODELS.get(model)
    if spec is None:
        raise ValueError(f"unknown model {model!r}")
    if spec["kind"] == "ollama":
        # reasoning runs generate far more tokens, so give them a longer leash
        return OllamaProvider(
            model=spec["id"], think=spec["think"], timeout=600.0 if spec["think"] else 120.0
        )
    return ClaudeProvider(spec["id"])


def tutorial_provider_for(model: str, source_len: int) -> ModelProvider:
    """The same model toggle as every other studio, but an Ollama provider gets a context window
    sized to the Knowledge Graph source. Measured live: `provider_for`'s default (unset num_ctx)
    let Ollama's small default context silently truncate the "respond with ONLY JSON" system
    prompt off a 37k-char transcript, so the model answered in prose instead of the required
    schema — the gate correctly rejected it, but every long source would fail the same way.
    ~3 chars/token, rounded up to the next 2k, with headroom for the system prompt and the
    JSON response itself; capped so a pathological source can't demand unbounded local RAM."""
    spec = MODELS.get(model)
    if spec is None:
        raise ValueError(f"unknown model {model!r}")
    if spec["kind"] != "ollama":
        return ClaudeProvider(spec["id"])
    num_ctx = max(4096, min(32768, -(-((source_len // 3) + 4096) // 2048) * 2048))
    return OllamaProvider(
        model=spec["id"], think=spec["think"], timeout=600.0, num_ctx=num_ctx, num_predict=4096,
    )
