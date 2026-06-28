"""P31c2 — real accounts behind the wedge's auth seam.

Identity becomes self-service, but the contract the wedge depends on is unchanged: `tenant_for` turns
a token into a tenant id or raises `Unauthorized`, so an account holder's run is isolated/persisted/
gated exactly as a static-token tenant's was. The security floor is asserted, not assumed: passwords
and tokens are never stored in the clear, wrong credentials are indistinguishable, sessions expire.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from engine.model import ScriptedProvider
from hub.accounts import AccountStore, BadCredentials, EmailTaken, WeakCredentials
from hub.wedge import Unauthorized, Wedge


def _store(tmp_path, **kw) -> AccountStore:
    return AccountStore(tmp_path / "accounts.db", **kw)


# --- signup ----------------------------------------------------------------------------------

def test_signup_returns_a_path_safe_tenant_id(tmp_path):
    from hub.wedge import _TENANT_RE
    uid = _store(tmp_path).signup("Alice@Example.com", "hunter2hunter")
    assert _TENANT_RE.match(uid)  # a user id is always a valid tenant directory


def test_duplicate_email_is_rejected_case_insensitively(tmp_path):
    s = _store(tmp_path)
    s.signup("a@b.com", "password1")
    with pytest.raises(EmailTaken):
        s.signup("A@B.com", "password2")  # normalized to the same address


def test_weak_credentials_are_refused(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(WeakCredentials):
        s.signup("not-an-email", "password1")
    with pytest.raises(WeakCredentials):
        s.signup("a@b.com", "short")


# --- login / sessions ------------------------------------------------------------------------

def test_login_issues_a_token_that_resolves_to_the_tenant(tmp_path):
    s = _store(tmp_path)
    uid = s.signup("a@b.com", "password1")
    token = s.login("a@b.com", "password1")
    assert s.tenant_for(f"Bearer {token}") == uid


def test_wrong_password_and_unknown_email_both_raise_badcredentials(tmp_path):
    s = _store(tmp_path)
    s.signup("a@b.com", "password1")
    with pytest.raises(BadCredentials):
        s.login("a@b.com", "wrongpassword")
    with pytest.raises(BadCredentials):
        s.login("ghost@b.com", "password1")  # indistinguishable from a wrong password


def test_logout_revokes_the_session(tmp_path):
    s = _store(tmp_path)
    s.signup("a@b.com", "password1")
    token = s.login("a@b.com", "password1")
    s.logout(f"Bearer {token}")
    with pytest.raises(Unauthorized):
        s.tenant_for(f"Bearer {token}")


def test_expired_session_is_rejected(tmp_path):
    s = _store(tmp_path, session_ttl=timedelta(seconds=-1))  # already expired on issue
    s.signup("a@b.com", "password1")
    token = s.login("a@b.com", "password1")
    with pytest.raises(Unauthorized):
        s.tenant_for(f"Bearer {token}")


def test_unknown_and_missing_tokens_are_unauthorized(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(Unauthorized):
        s.tenant_for(None)
    with pytest.raises(Unauthorized):
        s.tenant_for("Bearer nonsense")


# --- the security floor: nothing sensitive is stored in the clear ----------------------------

def test_password_and_token_are_never_stored_in_plaintext(tmp_path):
    s = _store(tmp_path)
    s.signup("a@b.com", "sup3rSecretPW")
    token = s.login("a@b.com", "sup3rSecretPW")
    blob = (tmp_path / "accounts.db").read_bytes()
    assert b"sup3rSecretPW" not in blob          # password hashed (scrypt)
    assert token.encode() not in blob            # only the SHA-256 of the token is stored


# --- the seam: an AccountStore IS an Authenticator, so the wedge runs unchanged ----------------

def test_wedge_runs_under_account_auth(tmp_path):
    spec = json.dumps({"function_name": "add", "description": "add two numbers",
                       "signature": "def add(a, b)",
                       "cases": [{"args": [1, 2], "expected": 3}]})
    s = _store(tmp_path / "acct")
    uid = s.signup("dev@b.com", "password1")
    token = s.login("dev@b.com", "password1")

    provider = lambda: ScriptedProvider({"spec": spec, "developer": "def add(a, b):\n    return a + b\n"})
    wedge = Wedge(tmp_path / "data", provider, s, sandbox_check=lambda: True)  # AccountStore as auth
    res = wedge.submit(authorization=f"Bearer {token}", goal="add two numbers")
    assert res.accepted and res.tenant == uid
    assert (tmp_path / "data" / "tenants" / uid).exists()  # isolated under the account's own id


# --- HTTP: signup -> login -> submit, end to end ----------------------------------------------

def test_http_auth_flow(tmp_path, monkeypatch):
    from engine.executor import ContainerExecutor
    from fastapi.testclient import TestClient

    from hub.app import create_app

    monkeypatch.setattr("engine.executor.default_executor", lambda: ContainerExecutor())
    monkeypatch.setenv("VERITAS_ACCOUNTS", "1")
    spec = json.dumps({"function_name": "add", "description": "add two numbers",
                       "signature": "def add(a, b)",
                       "cases": [{"args": [1, 2], "expected": 3}]})
    provider = ScriptedProvider({"spec": spec, "developer": "def add(a, b):\n    return a + b\n"})
    client = TestClient(create_app(data_dir=tmp_path, provider=provider))

    assert client.get("/api/wedge/status").json()["accounts"] is True
    assert client.post("/api/auth/signup", json={"email": "a@b.com", "password": "password1"}).status_code == 200
    assert client.post("/api/auth/signup", json={"email": "a@b.com", "password": "password2"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "a@b.com", "password": "nope"}).status_code == 401

    token = client.post("/api/auth/login", json={"email": "a@b.com", "password": "password1"}).json()["token"]
    r = client.post("/api/wedge/submit", json={"goal": "add two numbers"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["accepted"]
