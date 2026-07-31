"""hub/commons_datahub_emit.py — offline, deterministic (no live DataHub needed).

What matters to test: the emitter refuses anything that isn't an actual
human-vouched source record (never lets a different category or trust level
through under the honesty tag), and the owner URN it derives from a
record's channel is stable and safely slugified.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "datahub",
    reason="acryl-datahub needs Python 3.12 here (pydantic-core has no 3.14 wheel yet) — "
    "run this file with .venv-datahub, not the repo's main .venv",
)

from engine.memory import MemoryRecord
from hub.commons_datahub_emit import _owner_urn, _record_urn, emit_source_record


def _source_record(**overrides) -> MemoryRecord:
    record = MemoryRecord.from_source(
        url="https://example.com/video",
        transcript="some transcript text",
        channel="Example Channel",
        title="Example Title",
        captured_why="unit test fixture",
    )
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def test_emit_source_record_refuses_non_source_category():
    record = _source_record()
    record.category = "artifact"  # not a Second Brain source at all
    with pytest.raises(ValueError, match="not a human-vouched source record"):
        emit_source_record(emitter=None, record=record)  # type: ignore[arg-type]


def test_emit_source_record_refuses_untagged_trust():
    record = _source_record()
    record.provenance["trust"] = "unverified"  # tampered — no longer P28-compliant
    with pytest.raises(ValueError, match="not a human-vouched source record"):
        emit_source_record(emitter=None, record=record)  # type: ignore[arg-type]


def test_owner_urn_slugifies_channel_and_falls_back_when_absent():
    assert _owner_urn("CS102") == "urn:li:corpGroup:veritas-secondbrain-cs102"
    assert _owner_urn("Some Channel!") == "urn:li:corpGroup:veritas-secondbrain-some-channel"
    assert _owner_urn("") == "urn:li:corpGroup:veritas-secondbrain"


def test_record_urn_is_stable_and_scoped_to_the_veritas_platform():
    record = _source_record()
    urn = _record_urn(record)
    assert urn == f"urn:li:dataset:(urn:li:dataPlatform:veritas,secondbrain-{record.id},PROD)"
