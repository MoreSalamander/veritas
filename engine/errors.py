"""Shared error types for the model/embedding boundary.

Deliberately a leaf module with zero imports from the rest of `engine/` — both
`engine/model.py` and `engine/embed.py` need to raise the same typed failure,
but `engine/model.py` is itself imported by `engine/run.py`, which is imported
by `engine/memory.py`, which is imported by `engine/embed.py`. Putting the
shared type here (rather than in `model.py`, which `embed.py` would then have
to import) avoids that cycle entirely.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Raised by any `ModelProvider.propose()` or `Embedder.embed()` implementation
    when the underlying call fails for a reason the caller should be able to catch
    without knowing which concrete provider is in use — the whole point of the
    model/embedding seams.

    Local HTTP providers (Ollama, LM Studio) previously let raw `urllib.error.URLError`,
    `TimeoutError`, `json.JSONDecodeError`, and `KeyError`/`IndexError` (a malformed
    response body) escape directly. That's fine for a human watching a traceback, but
    it means the retry loop and the build pipeline — both written against
    `ModelProvider`/`Embedder` as abstractions, not against any one provider's
    transport — had no single type to catch. `ProviderError` is that type;
    `__cause__` still carries the original exception for anyone who needs the
    low-level detail (`str(exc.__cause__)`)."""
