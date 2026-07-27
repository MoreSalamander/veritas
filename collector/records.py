"""The generic envelope every source's own records get collected into.

Deliberately NOT a copy of each domain's own spec (an `OpportunitySpec`, an
`AllocationItem`, or whatever a future source's own shape is) — `payload_ref`
holds only a minimal pointer/summary. What Entropy's own store needs to
reason about is uniform across every source: where it came from, whether the
crossing was legitimate, and who (or what check) admitted it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AdmissionState(str, Enum):
    PENDING = "pending"
    ADMITTED = "admitted"
    DECLINED = "declined"


def record_id(source: str, source_ref: str) -> str:
    """Deterministic, idempotent: re-collecting the same source record always
    produces the same id, so `CollectorStore.upsert` can tell "seen before"
    from "new" without a separate lookup table."""
    return hashlib.sha1(f"{source}|{source_ref}".encode()).hexdigest()[:16]


class EntropyRecord(BaseModel):
    # extra="forbid" for the same reason OpportunitySpec uses it: a field-name
    # typo or a reader drifting out of sync with this shape should be a loud
    # ValidationError, not a silently-dropped field.
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str  # collector_sources.json key, e.g. "crypto_hunter"
    source_ref: str  # the origin record's own id
    kind: str  # SOURCES[source].kind — looked up in readers.KIND_READERS
    collected_at: datetime

    admitted: bool = False
    admitted_at: datetime | None = None
    admitted_by: str | None = None  # "auto:structural-check" | a user/tenant id | "operator"
    state: AdmissionState = AdmissionState.PENDING

    # Copied GateEvidence-shaped dicts from the source — this is what the
    # structural gate inspects. Never re-validated against the source's own
    # domain model; only checked for the shape every source's evidence must
    # carry (see collector/gate.py).
    verification: list[dict[str, Any]] = Field(default_factory=list)

    # A minimal pointer/summary, not the full domain object.
    payload_ref: dict[str, Any] = Field(default_factory=dict)
