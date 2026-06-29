"""P31c2 — real, self-service identity behind the wedge's auth seam.

c1 proved isolation with STATIC env tokens. This makes identity real: a person signs up, logs in,
and gets a session token — and that token resolves to a tenant id exactly the way the env tokens did,
so the wedge is unchanged and c1's per-tenant sandbox + DB isolation carries straight over (a user IS
a tenant). `AccountStore` satisfies the `Authenticator` protocol (`tenant_for`), so it drops in
wherever `WedgeAuth` did.

Security the store gets right by construction:
  • passwords are scrypt-hashed with a per-user random salt — the plaintext is never stored;
  • a session token is random (`secrets`), and only its SHA-256 hash is persisted — a DB leak exposes
    no live token;
  • every credential comparison is constant-time (`hmac.compare_digest`);
  • sessions carry an expiry and are rejected past it;
  • generated user ids are path-safe, so a user id is always a valid tenant directory.

Storage is one SQLite file, the same stdlib pattern as the DB-backed memory (P31b). Nothing here
touches a payment processor — quotas/billing are c2b and beyond, and read from this identity, not the
other way round.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hub.wedge import Unauthorized, parse_bearer

# A user id becomes a tenant directory, so it must satisfy the wedge's tenant rule by construction.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# Login handle. We never send mail, so a username IS the identifier — just a unique handle + a format
# rule. 3–32 chars, starts alphanumeric, then letters/digits/dot/underscore/hyphen.
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
_MIN_PASSWORD = 8

# scrypt work factors. 128*n*r ≈ 16 MiB at n=2**14 — deliberately costly to brute-force, cheap once.
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32, maxmem=132 * 1024 * 1024)
_SESSION_TTL = timedelta(days=7)


class UsernameTaken(Exception):
    """Signup with a username that already has an account."""


class WeakCredentials(Exception):
    """A malformed username or a password under the minimum length — rejected before any account exists."""


class BadCredentials(Exception):
    """Login with an unknown username or a wrong password. Deliberately indistinguishable (no
    account enumeration): the caller cannot tell which of the two it was."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccountStore:
    """SQLite-backed users + sessions. Implements `tenant_for`, so it IS an `Authenticator`."""

    def __init__(self, db_path: Path | str, session_ttl: timedelta = _SESSION_TTL) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_ttl = session_ttl
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                " id TEXT PRIMARY KEY,"
                " email TEXT UNIQUE NOT NULL,"
                " pw_hash BLOB NOT NULL,"
                " pw_salt BLOB NOT NULL,"
                " created_at TEXT NOT NULL)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                " token_hash TEXT PRIMARY KEY,"   # sha256(token); the plaintext token is never stored
                " user_id TEXT NOT NULL,"
                " created_at TEXT NOT NULL,"
                " expires_at TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    # --- signup / login / logout ---------------------------------------------------------------

    def signup(self, username: str, password: str) -> str:
        """Create an account; returns the new user id (= tenant id). Refuses a weak credential
        before writing anything, and a duplicate username. (The DB column is still named `email` —
        an internal legacy name kept so a deployed DB needs no migration; it just holds the username.)"""
        username = username.strip().lower()
        if not _USERNAME_RE.match(username):
            raise WeakCredentials("a valid username is required (3–32 chars: letters, digits, . _ -)")
        if len(password) < _MIN_PASSWORD:
            raise WeakCredentials(f"password must be at least {_MIN_PASSWORD} characters")
        user_id = "u" + secrets.token_hex(8)  # path-safe, matches the tenant rule by construction
        salt = secrets.token_bytes(16)
        try:
            with self._connect() as con:
                con.execute(
                    "INSERT INTO users (id, email, pw_hash, pw_salt, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, _hash_password(password, salt), salt, _now().isoformat()),
                )
        except sqlite3.IntegrityError as exc:  # the UNIQUE(username) constraint
            raise UsernameTaken("that username is already taken") from exc
        return user_id

    def login(self, username: str, password: str) -> str:
        """Verify credentials and issue a session token (the only time the plaintext token exists).
        Wrong username and wrong password are indistinguishable to the caller."""
        username = username.strip().lower()
        with self._connect() as con:
            row = con.execute(
                "SELECT id, pw_hash, pw_salt FROM users WHERE email = ?", (username,)
            ).fetchone()
        # Always run a hash so timing doesn't reveal whether the username exists.
        salt = row["pw_salt"] if row else secrets.token_bytes(16)
        expected = row["pw_hash"] if row else b"\x00" * 32
        if not hmac.compare_digest(_hash_password(password, salt), expected) or row is None:
            raise BadCredentials("invalid username or password")
        token = secrets.token_urlsafe(32)
        now = _now()
        with self._connect() as con:
            con.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_hash_token(token), row["id"], now.isoformat(), (now + self.session_ttl).isoformat()),
            )
        return token

    def logout(self, authorization: str | None) -> None:
        """Revoke the session behind a token. Idempotent — logging out an unknown token is a no-op."""
        token = parse_bearer(authorization)
        if token:
            with self._connect() as con:
                con.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))

    # --- the auth seam -------------------------------------------------------------------------

    def tenant_for(self, authorization: str | None) -> str:
        """Resolve a bearer token to its user/tenant id, or raise `Unauthorized`. Expired sessions
        are rejected (and cleaned up) — the same contract `WedgeAuth.tenant_for` offers."""
        token = parse_bearer(authorization)
        if not token:
            raise Unauthorized("missing Authorization header")
        token_hash = _hash_token(token)
        with self._connect() as con:
            row = con.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if row is None:
                raise Unauthorized("unrecognized token")
            if datetime.fromisoformat(row["expires_at"]) <= _now():
                con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                raise Unauthorized("session expired")
            user_id = row["user_id"]
        if not _ID_RE.match(user_id):  # defense in depth; ids are generated path-safe
            raise Unauthorized("invalid tenant id")
        return str(user_id)
