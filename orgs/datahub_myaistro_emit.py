"""Stage 9 (Metadata Operating System) emitter: the proof that "every
system contributes metadata into a shared graph" isn't a claim made about
Veritas alone. This reads myAIstro's OWN SOT — a completely separate
project, own repo, own backend, own storage format
(~/myAIstro/backend/memory_store.json, a flat JSON array) — directly, and
publishes each lesson as a DataHub entity.

Deliberately NOT routed through Veritas's Second Brain (hub/
commons_datahub_emit.py already covers that path, on lessons re-imported
INTO Veritas). This module reads myAIstro's canonical store straight, the
same read-only-direct-access pattern as orgs/datahub_opportunity_emit.py
reading crypto-hunter's own datahub.sqlite3 — proving a second, genuinely
independent system can emit into the same shared graph on its own, not
that Veritas can re-export data it already imported.

Git manages myAIstro's source (a real Dataset via Stage 2's repository
cataloging); this module is the piece of Stage 9's division of labor
that's actually new: myAIstro's application DATA joining DataHub's
relationship/provenance graph, while myAIstro's own JSON file remains the
system of record for that data — DataHub stores the metadata ABOUT it,
not a copy competing to be canonical.
"""

from __future__ import annotations

import json
from pathlib import Path

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SubTypesClass,
)

GMS_SERVER = "http://localhost:8080"
PLATFORM = "myaistro"
OWNER_URN = "urn:li:corpGroup:myaistro"


def _emit(emitter: DatahubRestEmitter, urn: str, aspect) -> None:
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def emit_myaistro_lessons(store_path: Path, gms_server: str = GMS_SERVER) -> list[str]:
    """Read myAIstro's real memory_store.json directly and publish every
    lesson as a DataHub entity, owned by myaistro (not veritas). Returns
    the emitted URNs."""
    entries = json.loads(store_path.read_text())
    ownership = OwnershipClass(
        owners=[OwnerClass(owner=OWNER_URN, type=OwnershipTypeClass.DATAOWNER)]
    )

    emitter = DatahubRestEmitter(gms_server=gms_server)
    urns: list[str] = []
    try:
        for entry in entries:
            event_id = entry.get("event_id", "unknown")
            urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},lesson-{event_id},PROD)"
            urns.append(urn)
            _emit(
                emitter,
                urn,
                DatasetPropertiesClass(
                    name=entry.get("lesson", "untitled"),
                    description=entry.get("summary") or "",
                    customProperties={
                        "course": entry.get("course", ""),
                        "week": str(entry.get("week", "")),
                        "key_concepts": ", ".join(entry.get("key_concepts") or []),
                        "code_block_count": str(len(entry.get("code_blocks") or [])),
                        "validation_score": str(entry.get("validation_score", "")),
                        "created_at": entry.get("created_at", ""),
                    },
                ),
            )
            _emit(emitter, urn, SubTypesClass(typeNames=["Lesson"]))
            _emit(emitter, urn, ownership)
        return urns
    finally:
        emitter.close()


if __name__ == "__main__":
    import sys

    store = Path.home() / "myAIstro" / "backend" / "memory_store.json"
    urns = emit_myaistro_lessons(store)
    print(f"emitted {len(urns)} myAIstro lessons — a second system, own platform, own ownership", file=sys.stderr)
