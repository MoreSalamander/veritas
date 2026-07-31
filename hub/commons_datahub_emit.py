"""Knowledge Graph -> DataHub emitter: publishes human-vouched commons source
records as real DataHub datasets, closing the loop between the two halves
of this session's work — orgs/datahub_emit.py publishes Hunter-org verdicts,
this publishes the Knowledge Graph's curated sources, onto the same platform.

DESIGN NOTE — the tag must say what human-vouched actually means, not just
that it exists. engine/memory.py's own doctrine (P28) is explicit: a human
vouching for a source means "worth keeping," never "true" — a consumer may
only cite it as an attributed claim ("Source X states Y"), never assert its
content as fact (orgs/research_studio's VouchedAttributionGate enforces this
downstream in Veritas itself). The VeritasHumanVouchedSource tag's
description states this contract directly, so anyone browsing DataHub sees
the same honesty constraint Veritas enforces internally — this is what makes
the emit correct, not just present.

No lineage edges here: unlike orgs/datahub_emit.py's org/outcome hierarchy,
commons sources have no natural parent — each is a standalone human
curation, not a child of some larger run.
"""

from __future__ import annotations

import re

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    TagAssociationClass,
    TagPropertiesClass,
)

from engine.memory import MemoryRecord

GMS_SERVER = "http://localhost:8080"
PLATFORM = "veritas"

TAG_NAME = "VeritasHumanVouchedSource"
TAG_DESCRIPTION = (
    "A human curated this source (Veritas P28) — vouches for it being worth "
    "keeping, NOT for the truth of its claims. May ground only an attributed "
    "claim (\"Source X states Y\"), never an asserted fact."
)

_OWNER_SAFE = re.compile(r"[^a-z0-9-]+")


def _owner_urn(channel: str) -> str:
    """A stable corpGroup per source channel, falling back to a generic
    Knowledge Graph owner when a record has no channel (e.g. a pasted-transcript
    or local-file source)."""
    slug = _OWNER_SAFE.sub("-", channel.strip().lower()).strip("-") if channel else ""
    return f"urn:li:corpGroup:veritas-secondbrain-{slug}" if slug else "urn:li:corpGroup:veritas-secondbrain"


def _record_urn(record: MemoryRecord) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},secondbrain-{record.id},PROD)"


def _emit(emitter: DatahubRestEmitter, urn: str, aspect) -> None:
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def emit_source_record(emitter: DatahubRestEmitter, record: MemoryRecord) -> str:
    """Publish one human-vouched commons record to DataHub. Returns its URN."""
    if record.category != "source" or record.provenance.get("trust") != "human-vouched":
        raise ValueError(f"{record.id} is not a human-vouched source record — refusing to emit it as one")

    urn = _record_urn(record)
    _emit(
        emitter,
        urn,
        DatasetPropertiesClass(
            name=record.title,
            description=record.provenance.get("captured_why") or "",
            externalUrl=record.provenance.get("url"),
            customProperties={
                "channel": record.provenance.get("channel") or "",
                "url": record.provenance.get("url") or "",
            },
        ),
    )
    _emit(
        emitter,
        urn,
        OwnershipClass(
            owners=[
                OwnerClass(
                    owner=_owner_urn(record.provenance.get("channel") or ""),
                    type=OwnershipTypeClass.DATAOWNER,
                )
            ]
        ),
    )
    tag_urn = f"urn:li:tag:{TAG_NAME}"
    _emit(emitter, tag_urn, TagPropertiesClass(name=TAG_NAME, description=TAG_DESCRIPTION))
    _emit(emitter, urn, GlobalTagsClass(tags=[TagAssociationClass(tag=tag_urn)]))
    return urn


def emit_source_records(records: list[MemoryRecord], gms_server: str = GMS_SERVER) -> list[str]:
    """Publish many commons records in one emitter session. Returns their URNs, in order."""
    emitter = DatahubRestEmitter(gms_server=gms_server)
    try:
        return [emit_source_record(emitter, record) for record in records]
    finally:
        emitter.close()
