"""Per-"kind" readers — real read-only reads into another repo's own DataHub.

Adapted directly from opportunity-agency-ai/engine/bridge.py's proven posture:
a real `mode=ro` SQLite connection (never the writable-by-default connection
a domain package's own store class would open), per-row try/except so one
malformed row can't corrupt a whole source's read, and a schema mismatch
degrades to an empty list with a loud print rather than raising out of the
collector.

A new source "kind" (e.g. whatever a future non-Opportunity-shaped manager's
own store looks like) plugs in as one new function registered in
KIND_READERS — the collector orchestrator never needs to change.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone

from .records import EntropyRecord, record_id
from .sources import SourceConfig, db_path_for

ReaderFn = Callable[[SourceConfig], "list[EntropyRecord]"]


def read_hunter_engine(cfg: SourceConfig) -> list[EntropyRecord]:
    """Reads a hunter_engine-shaped DataHub's `opportunities` table — the
    exact schema every Hunter engine (crypto/free-money/collectible) shares,
    per hunter_engine.store.DataHub. Only verified records are collectible;
    a candidate hasn't cleared its own source's gate yet, so there's nothing
    to admit."""
    db_path = db_path_for(cfg)
    if not db_path.exists():
        return []
    now = datetime.now(timezone.utc)
    out: list[EntropyRecord] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        print(f"[collector] could not open {cfg.name!r} at {db_path}: {exc}")
        return []
    try:
        rows = conn.execute(
            "SELECT id, spec_json FROM opportunities WHERE trust_status = 'verified'"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"[collector] schema mismatch reading {cfg.name!r} from {db_path}: {exc}")
        return []
    finally:
        conn.close()

    for opp_id, spec_json in rows:
        try:
            spec = json.loads(spec_json)
            out.append(
                EntropyRecord(
                    id=record_id(cfg.name, opp_id),
                    source=cfg.name,
                    source_ref=opp_id,
                    kind=cfg.kind,
                    collected_at=now,
                    verification=spec.get("verification") or [],
                    payload_ref={
                        "name": spec.get("name"),
                        "type": spec.get("type"),
                        "cost_usd_est": spec.get("cost_usd_est"),
                        "payout_usd_est": (spec.get("outcome") or {}).get("payout_usd_est"),
                    },
                )
            )
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
            # One malformed row must not corrupt this source's whole read.
            print(f"[collector] skipping a malformed record from {cfg.name!r} ({opp_id!r}): {exc}")
            continue
    return out


def read_opportunity_hub(cfg: SourceConfig) -> list[EntropyRecord]:
    """Reads an Opportunity-shaped hub's `allocations` table (one row per
    day, record_json = an AllocationRecord). Explodes each day's items into
    one EntropyRecord per AllocationItem. Opportunity has no item-level
    GateEvidence of its own — the underlying opportunity was already gated by
    its OWN source engine before Opportunity ever saw it — so this reader
    synthesizes one structural entry describing the item's own required-field
    shape, which is exactly what the admission gate needs to check: did this
    item actually come through Opportunity's own allocation process with the
    fields that process guarantees."""
    db_path = db_path_for(cfg)
    if not db_path.exists():
        return []
    now = datetime.now(timezone.utc)
    out: list[EntropyRecord] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        print(f"[collector] could not open {cfg.name!r} at {db_path}: {exc}")
        return []
    try:
        rows = conn.execute("SELECT date, record_json FROM allocations").fetchall()
    except sqlite3.OperationalError as exc:
        print(f"[collector] schema mismatch reading {cfg.name!r} from {db_path}: {exc}")
        return []
    finally:
        conn.close()

    for date, record_json in rows:
        try:
            record = json.loads(record_json)
            for item in record.get("items") or []:
                required = ("engine", "opportunity_id", "name")
                shape_ok = all(item.get(k) for k in required)
                ref = f"{date}:{item.get('engine')}:{item.get('opportunity_id')}"
                out.append(
                    EntropyRecord(
                        id=record_id(cfg.name, ref),
                        source=cfg.name,
                        source_ref=ref,
                        kind=cfg.kind,
                        collected_at=now,
                        verification=[{
                            "check": "allocation-item-shape",
                            "passed": shape_ok,
                            "data": {"engine": item.get("engine"), "opportunity_id": item.get("opportunity_id")},
                        }],
                        payload_ref={
                            "date": date,
                            "engine": item.get("engine"),
                            "name": item.get("name"),
                            "cost_usd_est": item.get("cost_usd_est"),
                            "time_minutes_est": item.get("time_minutes_est"),
                        },
                    )
                )
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
            print(f"[collector] skipping a malformed allocation from {cfg.name!r} ({date!r}): {exc}")
            continue
    return out


KIND_READERS: dict[str, ReaderFn] = {
    "hunter_engine": read_hunter_engine,
    "opportunity_hub": read_opportunity_hub,
}
