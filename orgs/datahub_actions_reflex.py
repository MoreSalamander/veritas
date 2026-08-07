"""The reflex: DataHub Actions as the operating system's interrupts.

Everything upstream WRITES verdicts into the graph (gate results as
AssertionRunEvent aspects) and, since the read path landed, consults it
before ruling. This module is the third leg: the graph CAUSES behavior.
A DataHub Actions pipeline subscribes to the metadata change log; when a
gate-failure assertion lands anywhere in the graph, the reflex fires —

  1. the failing dataset is tagged ``GateRejected`` so the rejection is
     visible (and filterable) right on the asset, and
  2. the event is appended to the reflex log (``reflexes.jsonl``), the
     OS's interrupt record.

This is the same Actions framework our own Vending Machine teaches in the
"DataHub 201" lesson — the system now runs what it stocks. Run it with:

    PYTHONPATH=. .venv-datahub/bin/datahub actions -c orgs/reflex_action.yaml

The action is deliberately narrow: it never creates facts (the verdict
already happened; the tag restates it), so a reflex misfire can annotate
but never decide. Decisions stay with the gates.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    GlobalTagsClass,
    TagAssociationClass,
    TagPropertiesClass,
)
from datahub_actions.action.action import Action
from datahub_actions.event.event_envelope import EventEnvelope
from datahub_actions.pipeline.pipeline_context import PipelineContext

REJECTED_TAG = "GateRejected"
_TAG_URN = f"urn:li:tag:{REJECTED_TAG}"


class VeritasReflexAction(Action):
    """Tag gate failures where they land; log every verdict event."""

    def __init__(self, config: dict[str, Any], ctx: PipelineContext) -> None:
        self.ctx = ctx
        gms = config.get("gms") or os.environ.get("DATAHUB_GMS", "http://localhost:8080")
        self.emitter = DatahubRestEmitter(gms_server=gms)
        self.log_path = Path(config.get("log_path") or "hub_data/reflexes.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # The tag must exist with an honest description before it is applied.
        self.emitter.emit(
            MetadataChangeProposalWrapper(
                entityUrn=_TAG_URN,
                aspect=TagPropertiesClass(
                    name=REJECTED_TAG,
                    description=(
                        "Applied by the reflex pipeline (DataHub Actions) the moment a "
                        "hard-gate failure assertion lands on this asset. Restates the "
                        "gate's verdict; never a verdict of its own."
                    ),
                ),
            )
        )

    @classmethod
    def create(cls, config_dict: dict[str, Any], ctx: PipelineContext) -> "VeritasReflexAction":
        return cls(config_dict or {}, ctx)

    # ------------------------------------------------------------------ act

    def act(self, event: EventEnvelope) -> None:
        parsed = self._parse_assertion_run(event)
        if parsed is None:
            return
        assertee, result_type, run_id = parsed
        entry = {
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": "assertion-run",
            "assertee": assertee,
            "result": result_type,
            "run_id": run_id,
        }
        if result_type == "FAILURE" and assertee:
            self.emitter.emit(
                MetadataChangeProposalWrapper(
                    entityUrn=assertee,
                    aspect=GlobalTagsClass(tags=[TagAssociationClass(tag=_TAG_URN)]),
                )
            )
            entry["reflex"] = f"tagged {REJECTED_TAG}"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _parse_assertion_run(
        self, event: EventEnvelope
    ) -> Optional[tuple[str, str, str]]:
        """Extract (asserteeUrn, result type, run id) from an
        assertionRunEvent metadata-change-log entry; None for anything else."""
        raw = getattr(event, "event", None)
        aspect_name = getattr(raw, "aspectName", None)
        if aspect_name != "assertionRunEvent":
            return None
        aspect = getattr(raw, "aspect", None)
        value = getattr(aspect, "value", None)
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        try:
            body = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
        result = (body.get("result") or {}).get("type") or body.get("status") or ""
        return (
            body.get("asserteeUrn") or "",
            str(result),
            body.get("runId") or "",
        )

    def close(self) -> None:
        self.emitter.close()
