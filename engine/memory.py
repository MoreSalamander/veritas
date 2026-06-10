"""Institutional memory — the only thing that persists, and the thing that learns.

Validated artifacts become organizational knowledge. Rejected artifacts become
failure records. Both are kept, because the organization learns from what it
accepted *and* what it refused (README §3, the Persist step).

Storage reuses the proven MoreSalamander shape: one file per record, YAML
frontmatter + markdown body, plus a human-readable index. Retrieval (surfacing a
past failure when a similar task starts) is Phase 3 — for now we persist honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.artifact import Artifact, _new_id, _now


@dataclass
class MemoryRecord:
    category: str  # "artifact" | "failure" | (later: decision/lesson/constraint/outcome)
    title: str
    body: str
    source_artifact_id: str | None = None
    tags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: _new_id("mem"))
    created_at: str = field(default_factory=_now)

    @classmethod
    def from_accepted_artifact(cls, artifact: Artifact) -> "MemoryRecord":
        return cls(
            category="artifact",
            title=f"[{artifact.type}] by {artifact.owner}",
            body=artifact.payload,
            source_artifact_id=artifact.id,
            tags=[artifact.type, "accepted"],
            provenance=_provenance_dict(artifact),
        )

    @classmethod
    def from_rejected_artifact(cls, artifact: Artifact, reason: str) -> "MemoryRecord":
        prov = _provenance_dict(artifact)
        prov["rejected_because"] = reason
        return cls(
            category="failure",
            title=f"[REJECTED {artifact.type}] by {artifact.owner}",
            body=f"Rejected.\n\nReason: {reason}\n\n--- proposed payload ---\n{artifact.payload}",
            source_artifact_id=artifact.id,
            tags=[artifact.type, "rejected"],
            provenance=prov,
        )


def _provenance_dict(artifact: Artifact) -> dict[str, Any]:
    p = artifact.provenance
    return {
        "created_by": p.created_by,
        "rationale": p.rationale,
        "accepted_because": p.accepted_because,
        "validated_by": [gr.gate_name for gr in p.gate_results],
        "gate_results": [
            {
                "gate": gr.gate_name,
                "determinism": gr.determinism.value,
                "passed": gr.passed,
                "evidence": gr.evidence,
            }
            for gr in p.gate_results
        ],
    }


class MemoryStore:
    """File-backed institutional memory rooted at `base_path`.

    institutional/  — accepted artifacts and (later) lessons & decisions
    failures/       — rejection records
    index.md        — one human-readable line per record
    """

    def __init__(self, base_path: Path | str) -> None:
        self.base = Path(base_path)
        self.institutional = self.base / "institutional"
        self.failures = self.base / "failures"
        self.index_path = self.base / "index.md"
        self.institutional.mkdir(parents=True, exist_ok=True)
        self.failures.mkdir(parents=True, exist_ok=True)

    def persist(self, record: MemoryRecord) -> Path:
        target_dir = self.failures if record.category == "failure" else self.institutional
        path = target_dir / f"{record.id}.md"
        path.write_text(self._render(record), encoding="utf-8")
        self._append_index(record, path)
        return path

    def _render(self, record: MemoryRecord) -> str:
        frontmatter = {
            "id": record.id,
            "category": record.category,
            "title": record.title,
            "source_artifact_id": record.source_artifact_id,
            "tags": record.tags,
            "created_at": record.created_at,
            "provenance": record.provenance,
        }
        front = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False).strip()
        return f"---\n{front}\n---\n\n{record.body}\n"

    def _append_index(self, record: MemoryRecord, path: Path) -> None:
        if not self.index_path.exists():
            self.index_path.write_text("# Institutional Memory — index\n\n", encoding="utf-8")
        rel = path.relative_to(self.base)
        line = f"- `[{record.category}]` {record.title} → [{rel}]({rel}) ({record.created_at})\n"
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(line)
