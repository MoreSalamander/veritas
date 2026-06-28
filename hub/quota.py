"""P31c2b — per-tenant quotas, and the usage ledger billing reads from.

The wedge already isolates and persists a tenant's runs; this bounds how many it may make, and keeps an
honest record of every one. `QuotaStore` satisfies the wedge's `Meter` seam (`check`/`record`/
`remaining`), so it drops in the way `AccountStore` did for auth — optional, env-gated, and invisible
to the rest of the wedge.

It is deliberately TWO things in one table:
  • a rate limiter — `check` refuses a run once a tenant has spent its allowance in the rolling window
    (the wedge maps that to HTTP 429); and
  • a billing substrate — every run is recorded with its timestamp and outcome, so a billing system can
    sum a tenant's usage over any period via `usage_for`. We do not charge money here (that needs a
    processor and the owner's keys); we make charging *possible* by recording the truth of what was used.

One SQLite file, the same stdlib pattern as the DB-backed memory (P31b) and accounts (P31c2a).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from hub.wedge import QuotaExceeded

_DEFAULT_WINDOW = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class QuotaPolicy:
    """How many runs a tenant may make per rolling window. `limit <= 0` means unmetered."""

    limit: int
    window: timedelta = _DEFAULT_WINDOW


class QuotaStore:
    """A per-tenant usage ledger that both enforces a ceiling and records billable usage."""

    def __init__(
        self, db_path: Path | str, policy: QuotaPolicy, clock: Callable[[], datetime] = _now
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy
        self.clock = clock  # injectable so window expiry is testable without sleeping
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS usage ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " tenant TEXT NOT NULL,"
                " at TEXT NOT NULL,"
                " accepted INTEGER NOT NULL,"
                " goal TEXT NOT NULL)"
            )
            con.execute("CREATE INDEX IF NOT EXISTS usage_tenant_at ON usage (tenant, at)")

    @classmethod
    def from_env(cls, db_path: Path | str) -> "QuotaStore | None":
        """Build a store from VERITAS_WEDGE_QUOTA (max runs) + VERITAS_WEDGE_QUOTA_WINDOW (seconds,
        default a day). Returns None when no positive limit is set — i.e. the wedge runs unmetered."""
        try:
            limit = int(os.environ.get("VERITAS_WEDGE_QUOTA", "0"))
        except ValueError:
            limit = 0
        if limit <= 0:
            return None
        try:
            window_s = int(os.environ.get("VERITAS_WEDGE_QUOTA_WINDOW", str(int(_DEFAULT_WINDOW.total_seconds()))))
        except ValueError:
            window_s = int(_DEFAULT_WINDOW.total_seconds())
        return cls(db_path, QuotaPolicy(limit, timedelta(seconds=max(1, window_s))))

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _used_in_window(self, tenant: str) -> int:
        since = (self.clock() - self.policy.window).isoformat()
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) AS n FROM usage WHERE tenant = ? AND at > ?", (tenant, since)
            ).fetchone()
        return int(row["n"])

    # --- the Meter seam ------------------------------------------------------------------------

    def check(self, tenant: str) -> None:
        """Refuse the run if the tenant has already used its full allowance in the current window."""
        if self.policy.limit <= 0:
            return
        if self._used_in_window(tenant) >= self.policy.limit:
            raise QuotaExceeded(
                f"quota exceeded: {self.policy.limit} runs per "
                f"{int(self.policy.window.total_seconds())}s window"
            )

    def record(self, tenant: str, accepted: bool, goal: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO usage (tenant, at, accepted, goal) VALUES (?, ?, ?, ?)",
                (tenant, self.clock().isoformat(), 1 if accepted else 0, goal),
            )

    def remaining(self, tenant: str) -> int:
        if self.policy.limit <= 0:
            return -1  # unmetered
        return max(0, self.policy.limit - self._used_in_window(tenant))

    # --- the billing substrate -----------------------------------------------------------------

    def usage_for(self, tenant: str, since: datetime | None = None) -> dict[str, Any]:
        """A tenant's usage — current-window counts for the UI, plus a billable total since `since`
        (e.g. the start of a billing period). The honest record a charge would be computed from."""
        clauses, params = ["tenant = ?"], [tenant]
        if since is not None:
            clauses.append("at >= ?")  # a billing-period start is inclusive
            params.append(since.isoformat())
        where = " AND ".join(clauses)
        with self._connect() as con:
            row = con.execute(
                f"SELECT COUNT(*) AS total, COALESCE(SUM(accepted), 0) AS accepted "
                f"FROM usage WHERE {where}", params
            ).fetchone()
        return {
            "tenant": tenant,
            "limit": self.policy.limit,
            "window_seconds": int(self.policy.window.total_seconds()),
            "used_in_window": self._used_in_window(tenant),
            "remaining": self.remaining(tenant),
            "billable_total": int(row["total"]),       # runs counted toward billing since `since`
            "billable_accepted": int(row["accepted"]),
        }
