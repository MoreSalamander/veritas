"""CollectorStore — Entropy's own DataHub. Same conventions as
hub/accounts.py's AccountStore and hub/quota.py's QuotaStore: one SQLite
file, plain sqlite3 (no ORM), schema-on-init via executescript.

A fresh connection per call, not one held from __init__ — FastAPI runs sync
route handlers in a threadpool, and a sqlite3 connection created in one
thread can't be used from another (this is the exact pattern AccountStore/
QuotaStore already use, for the same reason).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .records import AdmissionState, EntropyRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    admitted INTEGER NOT NULL DEFAULT 0,
    admitted_at TEXT,
    admitted_by TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    verification_json TEXT NOT NULL,
    payload_ref_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_state ON records(state);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);
"""

_COLUMNS = (
    "id, source, source_ref, kind, collected_at, admitted, admitted_at,"
    " admitted_by, state, verification_json, payload_ref_json"
)


def _row_to_record(row: tuple[object, ...]) -> EntropyRecord:
    (rid, source, source_ref, kind, collected_at, admitted, admitted_at,
     admitted_by, state, verification_json, payload_ref_json) = row
    return EntropyRecord(
        id=str(rid),
        source=str(source),
        source_ref=str(source_ref),
        kind=str(kind),
        collected_at=collected_at,  # type: ignore[arg-type]
        admitted=bool(admitted),
        admitted_at=admitted_at,  # type: ignore[arg-type]
        admitted_by=admitted_by,  # type: ignore[arg-type]
        state=AdmissionState(state),
        verification=json.loads(str(verification_json)),
        payload_ref=json.loads(str(payload_ref_json)),
    )


class CollectorStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def upsert(self, record: EntropyRecord) -> None:
        """Re-collecting an already-seen record refreshes collected_at and
        verification, but a decision already made — admitted or declined —
        is sticky: a re-collection must never silently revert a human's (or
        an earlier auto-admit's) call back to pending."""
        with self._connect() as con:
            existing_row = con.execute(
                "SELECT state FROM records WHERE id = ?", (record.id,)
            ).fetchone()
            if existing_row is not None and existing_row[0] != AdmissionState.PENDING.value:
                con.execute(
                    "UPDATE records SET collected_at = ?, verification_json = ?, payload_ref_json = ?"
                    " WHERE id = ?",
                    (
                        record.collected_at.isoformat(),
                        json.dumps(record.verification),
                        json.dumps(record.payload_ref),
                        record.id,
                    ),
                )
            else:
                con.execute(
                    f"INSERT INTO records ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(id) DO UPDATE SET"
                    " collected_at=excluded.collected_at, admitted=excluded.admitted,"
                    " admitted_at=excluded.admitted_at, admitted_by=excluded.admitted_by,"
                    " state=excluded.state, verification_json=excluded.verification_json,"
                    " payload_ref_json=excluded.payload_ref_json",
                    (
                        record.id, record.source, record.source_ref, record.kind,
                        record.collected_at.isoformat(), int(record.admitted),
                        record.admitted_at.isoformat() if record.admitted_at else None,
                        record.admitted_by, record.state.value,
                        json.dumps(record.verification), json.dumps(record.payload_ref),
                    ),
                )

    def get(self, record_id: str) -> EntropyRecord | None:
        with self._connect() as con:
            row = con.execute(
                f"SELECT {_COLUMNS} FROM records WHERE id = ?", (record_id,)
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_pending(self, limit: int = 200) -> list[EntropyRecord]:
        with self._connect() as con:
            rows = con.execute(
                f"SELECT {_COLUMNS} FROM records WHERE state = 'pending'"
                " ORDER BY collected_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def list_by_source(self, source: str) -> list[EntropyRecord]:
        with self._connect() as con:
            rows = con.execute(
                f"SELECT {_COLUMNS} FROM records WHERE source = ? ORDER BY collected_at DESC",
                (source,),
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def count_pending(self) -> int:
        with self._connect() as con:
            row = con.execute("SELECT COUNT(*) FROM records WHERE state = 'pending'").fetchone()
        return int(row[0]) if row is not None else 0

    def _decide(self, record_id: str, *, admitted: bool, by: str) -> EntropyRecord | None:
        with self._connect() as con:
            existing_row = con.execute(
                "SELECT state FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            if existing_row is None or existing_row[0] != AdmissionState.PENDING.value:
                # Unknown, or already decided — idempotent no-op, not an error
                # the caller has to special-case differently from "doesn't exist".
                return None
            now = datetime.now(timezone.utc)
            state = AdmissionState.ADMITTED if admitted else AdmissionState.DECLINED
            con.execute(
                "UPDATE records SET admitted = ?, admitted_at = ?, admitted_by = ?, state = ?"
                " WHERE id = ?",
                (int(admitted), now.isoformat(), by, state.value, record_id),
            )
            row = con.execute(f"SELECT {_COLUMNS} FROM records WHERE id = ?", (record_id,)).fetchone()
        return _row_to_record(row) if row is not None else None

    def approve(self, record_id: str, by: str) -> EntropyRecord | None:
        return self._decide(record_id, admitted=True, by=by)

    def decline(self, record_id: str, by: str) -> EntropyRecord | None:
        return self._decide(record_id, admitted=False, by=by)
