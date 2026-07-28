"""The API key tracker — inventory metadata only, never a secret value.

This module stores NOTHING secret. The actual key values live in the macOS
Keychain (via `security`, see scripts/keytracker_cli.py) — an already-
hardened, encrypted-at-rest, access-controlled OS primitive. This module's
job is the same as hub/accounts.py's or hub/quota.py's: track what exists,
in plain SQLite, with the same per-call-connection convention (a sqlite3
connection created in one thread can't cross into another, and FastAPI runs
sync routes in a threadpool).

No method here accepts or returns a secret value. That boundary is by
design, not by discipline: KeyRecord simply has no field capable of holding
one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class KeyRecord:
    id: str
    label: str
    provider: str
    keychain_account: str
    env_var_name: str
    used_by_repos: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_rotated_at: datetime | None = None
    status: str = "active"  # "active" | "revoked"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS keys (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    provider TEXT NOT NULL,
    keychain_account TEXT NOT NULL,
    env_var_name TEXT NOT NULL,
    used_by_repos TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_rotated_at TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);
"""

_COLUMNS = (
    "id, label, provider, keychain_account, env_var_name, used_by_repos,"
    " created_at, last_rotated_at, status"
)


def _row_to_record(row: tuple[object, ...]) -> KeyRecord:
    (kid, label, provider, keychain_account, env_var_name, used_by_repos_csv,
     created_at, last_rotated_at, status) = row
    return KeyRecord(
        id=str(kid),
        label=str(label),
        provider=str(provider),
        keychain_account=str(keychain_account),
        env_var_name=str(env_var_name),
        used_by_repos=[r for r in str(used_by_repos_csv).split(",") if r],
        created_at=datetime.fromisoformat(str(created_at)),
        last_rotated_at=datetime.fromisoformat(str(last_rotated_at)) if last_rotated_at else None,
        status=str(status),
    )


class KeyTrackerStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def upsert(self, record: KeyRecord) -> None:
        with self._connect() as con:
            con.execute(
                f"INSERT INTO keys ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " label=excluded.label, provider=excluded.provider,"
                " keychain_account=excluded.keychain_account, env_var_name=excluded.env_var_name,"
                " used_by_repos=excluded.used_by_repos, last_rotated_at=excluded.last_rotated_at,"
                " status=excluded.status",
                (
                    record.id, record.label, record.provider, record.keychain_account,
                    record.env_var_name, ",".join(record.used_by_repos),
                    record.created_at.isoformat(),
                    record.last_rotated_at.isoformat() if record.last_rotated_at else None,
                    record.status,
                ),
            )

    def get(self, key_id: str) -> KeyRecord | None:
        with self._connect() as con:
            row = con.execute(f"SELECT {_COLUMNS} FROM keys WHERE id = ?", (key_id,)).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_all(self) -> list[KeyRecord]:
        with self._connect() as con:
            rows = con.execute(f"SELECT {_COLUMNS} FROM keys ORDER BY created_at DESC").fetchall()
        return [_row_to_record(r) for r in rows]

    def mark_rotated(self, key_id: str) -> KeyRecord | None:
        now = datetime.now(timezone.utc)
        with self._connect() as con:
            con.execute("UPDATE keys SET last_rotated_at = ? WHERE id = ?", (now.isoformat(), key_id))
            row = con.execute(f"SELECT {_COLUMNS} FROM keys WHERE id = ?", (key_id,)).fetchone()
        return _row_to_record(row) if row is not None else None

    def revoke(self, key_id: str) -> KeyRecord | None:
        with self._connect() as con:
            con.execute("UPDATE keys SET status = 'revoked' WHERE id = ?", (key_id,))
            row = con.execute(f"SELECT {_COLUMNS} FROM keys WHERE id = ?", (key_id,)).fetchone()
        return _row_to_record(row) if row is not None else None
