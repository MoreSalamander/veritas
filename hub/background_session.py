"""Shared scaffold for the Hub's background-thread session classes.

`BenchSession`, `TuneSession`, `CreateSession`, `ProductionCreateSession`, and
`PlanSession` (all in `hub/app.py`) each drive one long-running operation on a
daemon thread and let an HTTP client poll or steer it by token. Before this
module existed, all five hand-rolled an identical
`lock` + `state` + `start()` + `snapshot()` (+ `_set()` for the three
interactive ones) scaffold — a real reviewer would ask why the same twelve
lines exist five times, since a bug in the locking pattern would need fixing
in five places instead of one.

`BackgroundSession` factors out exactly the part that was byte-for-byte
identical across all five (`lock`, `start()`, `_set()`) plus a sensible
default `snapshot()` (a plain shallow copy of `state`). Three subclasses need
a *deeper* copy of one nested mutable field in their snapshot (a list of
cells, a list-of-lists transcript) — those override `snapshot()`, call
`super().snapshot()` for the base copy, and then deep-copy just their own
field, rather than reimplementing the lock-guarded copy from scratch.
"""

from __future__ import annotations

import threading
from typing import Any


class BackgroundSession:
    """Base for a session that runs one operation on a background daemon
    thread and exposes its progress as a lock-guarded `state` dict.

    Subclasses must set `self.state` (typically in their own `__init__`,
    after calling `super().__init__(token)`) and must implement `_run(self)`
    — the method actually executed on the background thread."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {}

    def start(self) -> None:
        """Begin `_run` on a daemon thread. Fire-and-forget: the caller polls
        `snapshot()` for progress rather than awaiting this call."""
        threading.Thread(target=self._run, daemon=True).start()

    def snapshot(self) -> dict[str, Any]:
        """A lock-guarded, safe-to-mutate copy of `state` for the polling
        endpoint to return. Shallow: a subclass whose state contains a list
        or dict that `_run` appends/mutates in place (rather than replacing
        wholesale via `_set`) must override this and deep-copy that one
        field after calling `super().snapshot()`."""
        with self.lock:
            return dict(self.state)

    def _set(self, **fields: Any) -> None:
        """Lock-guarded, wholesale update of one or more top-level state
        fields — the common case for the three interactive sessions
        (Create/ProductionCreate/Plan), which replace a field's value rather
        than mutate it in place."""
        with self.lock:
            self.state.update(fields)

    def _run(self) -> None:
        """Executed on the background thread started by `start()`. Every
        subclass must override this; the base implementation exists only so
        the class is concrete enough for type-checking (it is never actually
        called — `start()` always targets the subclass's own `_run`)."""
        raise NotImplementedError
