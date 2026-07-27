"""Bounded, self-evicting registries for one-shot session/progress tokens.

Several endpoints in `hub/app.py` keep server-side state keyed by a one-shot
token — a run's live progress, a Create/Produce/Plan session, a Bench/Tune
session, a wedge submission, a brief — so a client can poll or resume it by
token. Before this module existed, those were plain `dict`s that grew for the
entire lifetime of the process: nothing ever removed an entry once its session
finished, so a long-running hosted process accumulates memory without bound —
every run anyone has ever started stays resident forever.

`ExpiringRegistry` is a drop-in replacement for that dict at every call site
that already existed (`registry[token] = value`, `registry.get(token)`,
`token in registry`, and in-place mutation of the value returned by
`__getitem__`/`.get()`) — no call site needs to change except the declaration.
Expiry is swept opportunistically on write rather than via a background
thread, which is simpler and sufficient here: these registries only grow
through user-initiated requests, so a write is guaranteed to happen
periodically whenever the registry is actually being used.
"""

from __future__ import annotations

import time
from typing import Generic, TypeVar

V = TypeVar("V")

# Known, accepted tradeoff: a session that is written once (`registry[token] =
# {...}`) and then only ever mutated in place (`registry[token]["field"] = x`)
# does not refresh its own expiry timestamp on those later mutations, because
# an in-place mutation on the object returned by __getitem__/get() never calls
# back through this class. In practice every session here either finishes
# within seconds (a single request/response) or minutes (a background thread
# streaming progress), so a generously long default TTL (see DEFAULT_MAX_AGE_SECONDS
# below) means this is never observed in practice — but it is why `touch()`
# exists, for a caller that wants a stronger guarantee for a specific registry.
DEFAULT_MAX_AGE_SECONDS = 6 * 60 * 60  # 6 hours: comfortably longer than any real session


class ExpiringRegistry(Generic[V]):
    """A `dict[str, V]`-shaped store where entries older than `max_age_seconds`
    are evicted automatically. Sweeps every `sweep_every` writes rather than on
    every single write, so the sweep's O(n) scan doesn't run on every request."""

    def __init__(self, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS, sweep_every: int = 20) -> None:
        self._max_age = max_age_seconds
        self._sweep_every = sweep_every
        self._writes_since_sweep = 0
        self._store: dict[str, tuple[float, V]] = {}

    def __setitem__(self, key: str, value: V) -> None:
        self._store[key] = (time.monotonic(), value)
        self._writes_since_sweep += 1
        if self._writes_since_sweep >= self._sweep_every:
            self.sweep_now()

    def __getitem__(self, key: str) -> V:
        return self._store[key][1]

    def get(self, key: str, default: V | None = None) -> V | None:
        entry = self._store.get(key)
        return entry[1] if entry is not None else default

    def __contains__(self, key: str) -> bool:
        return key in self._store

    def __len__(self) -> int:
        """Number of entries currently held, INCLUDING any that are expired but
        haven't been swept yet — call `sweep_now()` first for an exact count."""
        return len(self._store)

    def touch(self, key: str) -> None:
        """Refresh a key's age without changing its value. Only needed by a
        caller that mutates the stored value in place many times over a long
        span and wants a stronger guarantee than the generous default TTL
        already provides."""
        entry = self._store.get(key)
        if entry is not None:
            self._store[key] = (time.monotonic(), entry[1])

    def sweep_now(self) -> int:
        """Evict every expired entry immediately, regardless of the write
        counter. Returns the number of entries evicted. Exposed for tests and
        for any caller that wants a deterministic sweep point rather than
        waiting for the next `sweep_every`th write."""
        now = time.monotonic()
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self._max_age]
        for k in expired:
            del self._store[k]
        self._writes_since_sweep = 0
        return len(expired)
