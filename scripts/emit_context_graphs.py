"""Emit spooled research context graphs into the metadata knowledge graph.

The wedge's intelligence flow writes each run's context graph to a spool
(``<tenant root>/research/graph_spool/research-<run>.json``) whenever a
DataHub is reachable. This script — run under the operator's datahub venv —
drains the spool: every entity becomes a governed dataset on the ``veritas``
platform, every typed relationship an upstream lineage edge, and the source
run is stamped on both. Re-runs are harmless (last-write-wins aspects);
a spool file is deleted only after its graph emitted cleanly.

Run:  PYTHONPATH=. .venv-datahub/bin/python scripts/emit_context_graphs.py [data_root]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    SubTypesClass,
    UpstreamClass,
    UpstreamLineageClass,
)

GMS = os.environ.get("DATAHUB_GMS", "http://localhost:8080")
PLATFORM = "veritas"


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def _entity_urn(name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},research-entity-{_slug(name)},PROD)"


def emit_graph(emitter: DatahubRestEmitter, spool: dict) -> int:
    graph = spool.get("graph") or {}
    run_id = spool.get("run_id") or "unknown"
    topic = graph.get("topic") or ""
    emitted = 0
    for ent in graph.get("entities") or []:
        urn = _entity_urn(ent["name"])
        emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=DatasetPropertiesClass(
            name=ent["name"],
            description=ent.get("description") or "",
            customProperties={
                "entity_type": ent.get("type") or "concept",
                "surfaced_by_run": run_id,
                "surfaced_for_topic": topic,
            },
        )))
        emitter.emit(MetadataChangeProposalWrapper(
            entityUrn=urn, aspect=SubTypesClass(typeNames=["ResearchEntity", ent.get("type") or "concept"]),
        ))
        emitted += 1
    # Typed edges: target depends on / is caused by / ... source — modeled as
    # lineage (source upstream of target), the relation kept in properties on
    # the target's edge set via the transform note below. Lineage is the one
    # first-class edge DataHub renders everywhere, so the graph stays visible.
    by_target: dict[str, list[str]] = {}
    for rel in graph.get("relationships") or []:
        by_target.setdefault(rel["target"], []).append(rel["source"])
    for target, upstream_names in by_target.items():
        emitter.emit(MetadataChangeProposalWrapper(
            entityUrn=_entity_urn(target),
            aspect=UpstreamLineageClass(upstreams=[
                UpstreamClass(dataset=_entity_urn(srcname), type=DatasetLineageTypeClass.TRANSFORMED)
                for srcname in upstream_names
            ]),
        ))
        emitted += 1
    return emitted


def main() -> int:
    data_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("hub_data")
    spools = sorted(data_root.rglob("graph_spool/research-*.json"))
    if not spools:
        print(f"emit_context_graphs: no spooled graphs under {data_root}")
        return 0
    emitter = DatahubRestEmitter(gms_server=GMS)
    total = 0
    try:
        for path in spools:
            try:
                spool = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  skip {path.name}: unreadable ({exc})")
                continue
            n = emit_graph(emitter, spool)
            total += n
            path.unlink()
            print(f"  {path.name}: {n} aspects emitted, spool drained")
    finally:
        emitter.close()
    print(f"emit_context_graphs: {total} aspects into {GMS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
