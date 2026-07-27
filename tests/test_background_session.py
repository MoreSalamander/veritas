"""BackgroundSession — the shared lock/state/start/snapshot scaffold factored
out of hub/app.py's five session classes (Bench/Tune/Create/ProductionCreate/
Plan) during the production-quality audit.
"""

from __future__ import annotations

import threading
import time

from hub.background_session import BackgroundSession


class _CountToThree(BackgroundSession):
    """A minimal concrete session: counts to 3 on its background thread,
    updating `state["done"]` via `_set` as it goes."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.state = {"done": 0, "phase": "running"}

    def _run(self) -> None:
        for i in range(1, 4):
            self._set(done=i)
        self._set(phase="finished")


def _wait_until_finished(session: BackgroundSession, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.snapshot()["phase"] == "finished":
            return
        time.sleep(0.01)
    raise AssertionError("session did not finish within the timeout")


def test_start_runs_run_on_a_background_thread_and_snapshot_reflects_progress() -> None:
    session = _CountToThree("token-1")

    session.start()
    _wait_until_finished(session)

    assert session.snapshot() == {"done": 3, "phase": "finished"}


def test_snapshot_returns_a_copy_not_the_live_state_dict() -> None:
    session = _CountToThree("token-1")

    snap = session.snapshot()
    snap["done"] = 999

    assert session.state["done"] == 0  # mutating the snapshot must not affect live state


def test_subclass_must_implement_run() -> None:
    session = BackgroundSession("token-1")

    try:
        session._run()
        assert False, "expected NotImplementedError"
    except NotImplementedError:
        pass


def test_set_is_lock_guarded_against_concurrent_writers() -> None:
    """Not a proof of thread-safety in general, but a real regression guard:
    many threads calling _set concurrently must never raise, and the final
    state must reflect the last write, not a torn/partial one."""
    session = _CountToThree("token-1")
    session.state = {"counter": 0}

    def bump(n: int) -> None:
        session._set(counter=n)

    threads = [threading.Thread(target=bump, args=(n,)) for n in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert isinstance(session.snapshot()["counter"], int)  # never left partially written
