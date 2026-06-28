"""P31c2b — per-tenant quotas and the billable usage ledger.

Two jobs, one table: a RATE LIMITER (a tenant is refused once it spends its window's allowance — the
wedge maps that to 429) and a BILLING SUBSTRATE (every run is recorded with its time and outcome, so
usage over any period is summable). The window is asserted with an injected clock, no sleeping. The
limit binds per tenant (one tenant's spend never touches another's), and the wedge enforces it AFTER
the sandbox gate but BEFORE the run.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from engine.model import ScriptedProvider
from hub.quota import QuotaPolicy, QuotaStore
from hub.wedge import QuotaExceeded, Wedge, WedgeAuth


class _Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


def _store(tmp_path, limit=3, window=timedelta(days=1), clock=None) -> QuotaStore:
    return QuotaStore(tmp_path / "usage.db", QuotaPolicy(limit, window), clock=clock or _Clock())


# --- the rate limiter ------------------------------------------------------------------------

def test_check_passes_until_the_limit_then_refuses(tmp_path):
    s = _store(tmp_path, limit=2)
    s.check("alice"); s.record("alice", True, "g")   # 1
    s.check("alice"); s.record("alice", True, "g")   # 2
    with pytest.raises(QuotaExceeded):
        s.check("alice")                             # 3rd is over the limit


def test_remaining_counts_down(tmp_path):
    s = _store(tmp_path, limit=3)
    assert s.remaining("alice") == 3
    s.record("alice", True, "g")
    assert s.remaining("alice") == 2


def test_quota_is_per_tenant(tmp_path):
    s = _store(tmp_path, limit=1)
    s.check("alice"); s.record("alice", True, "g")
    with pytest.raises(QuotaExceeded):
        s.check("alice")
    s.check("bob")  # bob's allowance is untouched by alice's spend


def test_window_expiry_frees_the_allowance(tmp_path):
    clock = _Clock()
    s = _store(tmp_path, limit=1, window=timedelta(hours=1), clock=clock)
    s.check("alice"); s.record("alice", True, "g")
    with pytest.raises(QuotaExceeded):
        s.check("alice")
    clock.advance(hours=2)          # the earlier run rolls out of the window
    s.check("alice")                # allowed again
    assert s.remaining("alice") == 1


def test_limit_zero_is_unmetered(tmp_path):
    s = _store(tmp_path, limit=0)
    for _ in range(5):
        s.check("alice"); s.record("alice", True, "g")  # never raises
    assert s.remaining("alice") == -1


# --- the billing substrate -------------------------------------------------------------------

def test_usage_for_reports_window_and_billable_totals(tmp_path):
    clock = _Clock()
    s = _store(tmp_path, limit=10, window=timedelta(hours=1), clock=clock)
    s.record("alice", True, "g1")
    s.record("alice", False, "g2")
    clock.advance(hours=2)
    s.record("alice", True, "g3")                       # outside the rolling window, still billable
    u = s.usage_for("alice")
    assert u["used_in_window"] == 1 and u["remaining"] == 9   # only g3 is inside the 1h window now
    assert u["billable_total"] == 3 and u["billable_accepted"] == 2  # all-time billable count


def test_usage_for_since_bounds_the_billable_period(tmp_path):
    clock = _Clock()
    s = _store(tmp_path, limit=10, clock=clock)
    s.record("alice", True, "old")
    clock.advance(days=2)
    boundary = clock()                                  # a billing-period start
    s.record("alice", True, "new")
    assert s.usage_for("alice", since=boundary)["billable_total"] == 1  # only the post-boundary run


# --- from_env --------------------------------------------------------------------------------

def test_from_env_off_when_no_positive_limit(tmp_path, monkeypatch):
    monkeypatch.delenv("VERITAS_WEDGE_QUOTA", raising=False)
    assert QuotaStore.from_env(tmp_path / "u.db") is None


def test_from_env_builds_a_store(tmp_path, monkeypatch):
    monkeypatch.setenv("VERITAS_WEDGE_QUOTA", "5")
    monkeypatch.setenv("VERITAS_WEDGE_QUOTA_WINDOW", "3600")
    s = QuotaStore.from_env(tmp_path / "u.db")
    assert s is not None and s.policy.limit == 5 and s.policy.window == timedelta(seconds=3600)


# --- the wedge enforces it (after the sandbox gate) ------------------------------------------

def _wedge_provider() -> ScriptedProvider:
    spec = json.dumps({"function_name": "add", "description": "add two numbers",
                       "signature": "def add(a, b)", "cases": [{"args": [1, 2], "expected": 3}]})
    return ScriptedProvider({"spec": spec, "developer": "def add(a, b):\n    return a + b\n"})


def test_wedge_meters_runs_and_reports_remaining(tmp_path):
    meter = _store(tmp_path / "q", limit=2)
    auth = WedgeAuth({"tok": "alice"})
    w = Wedge(tmp_path / "data", _wedge_provider, auth, sandbox_check=lambda: True, meter=meter)

    r1 = w.submit(authorization="Bearer tok", goal="add two numbers")
    assert r1.accepted and r1.remaining == 1
    r2 = w.submit(authorization="Bearer tok", goal="add two numbers")
    assert r2.remaining == 0
    with pytest.raises(QuotaExceeded):
        w.submit(authorization="Bearer tok", goal="add two numbers")


def test_quota_is_checked_after_the_sandbox_gate(tmp_path):
    # no live sandbox => the run is refused for ISOLATION, never reaching the meter (no spend recorded)
    from hub.wedge import SandboxUnavailable
    meter = _store(tmp_path / "q", limit=1)
    w = Wedge(tmp_path / "data", _wedge_provider, WedgeAuth({"tok": "alice"}),
              sandbox_check=lambda: False, meter=meter)
    with pytest.raises(SandboxUnavailable):
        w.submit(authorization="Bearer tok", goal="add two numbers")
    assert meter.remaining("alice") == 1  # nothing was metered


# --- HTTP: 429 + the usage endpoint ----------------------------------------------------------

def test_http_429_and_usage(tmp_path, monkeypatch):
    from engine.executor import ContainerExecutor
    from fastapi.testclient import TestClient

    from hub.app import create_app

    monkeypatch.setattr("engine.executor.default_executor", lambda: ContainerExecutor())
    monkeypatch.setenv("VERITAS_WEDGE_TOKENS", "tok_alice:alice")
    monkeypatch.setenv("VERITAS_WEDGE_QUOTA", "1")
    client = TestClient(create_app(data_dir=tmp_path, provider=_wedge_provider()))
    hdr = {"Authorization": "Bearer tok_alice"}

    assert client.get("/api/wedge/status").json()["metered"] is True
    assert client.post("/api/wedge/submit", json={"goal": "add two numbers"}, headers=hdr).status_code == 200
    assert client.post("/api/wedge/submit", json={"goal": "add two numbers"}, headers=hdr).status_code == 429
    usage = client.get("/api/wedge/usage", headers=hdr).json()
    assert usage["metered"] and usage["used_in_window"] == 1 and usage["billable_total"] == 1
