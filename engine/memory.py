"""Institutional memory — the only thing that persists, and the thing that learns.

Validated artifacts become organizational knowledge. Rejected artifacts become
failure records. Both are kept, because the organization learns from what it
accepted *and* what it refused (README §3, the Persist step).

Storage reuses the proven MoreSalamander shape: one file per record, YAML
frontmatter + markdown body, plus a human-readable index. Retrieval (surfacing a
past failure when a similar task starts) is Phase 3 — for now we persist honestly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.artifact import Artifact, _new_id, _now

# Deterministic retrieval: overlap of meaningful tokens. Explainable and testable.
# An embedding-backed recall can slot in behind the same interface later.
_STOPWORDS = {
    "a", "an", "the", "of", "to", "and", "or", "that", "this", "returns", "return",
    "function", "func", "def", "is", "are", "for", "with", "in", "on", "be", "given",
    "value", "values", "number", "numbers", "integer", "string",
}


def _stem(word: str) -> str:
    # Just enough to make "reverses"/"strings" match "reverse"/"string". Not linguistics.
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9_]+", text.lower()):
        if len(word) <= 2:
            continue
        stem = _stem(word)
        if len(stem) > 2 and stem not in _STOPWORDS:
            out.add(stem)
    return out


def format_lessons(recalled: list["MemoryRecord"]) -> str | None:
    """Turn recalled failures/lessons into a prompt preamble. Org-agnostic — any
    org's proposers can be warned by the org's own past mistakes this way."""
    if not recalled:
        return None
    lines = ["Lessons from past attempts at similar goals (avoid repeating these):"]
    for record in recalled:
        reason = record.provenance.get("rejected_because")
        if not reason:
            reason = record.body.splitlines()[0] if record.body else record.title
        lines.append(f"- {record.title}: {reason}")
    return "\n".join(lines)


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
        "informed_by": list(p.informed_by),
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

    # --- retrieval: the org reading its own memory before it acts ---------------

    def load_all(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for directory in (self.institutional, self.failures):
            for path in sorted(directory.glob("*.md")):
                records.append(self._parse(path))
        return records

    def _parse(self, path: Path) -> MemoryRecord:
        text = path.read_text(encoding="utf-8")
        frontmatter: dict[str, Any] = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)  # maxsplit=2 keeps any '---' inside the body
            if len(parts) == 3:
                frontmatter = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
        return MemoryRecord(
            category=frontmatter.get("category", ""),
            title=frontmatter.get("title", ""),
            body=body,
            source_artifact_id=frontmatter.get("source_artifact_id"),
            tags=frontmatter.get("tags") or [],
            provenance=frontmatter.get("provenance") or {},
            id=frontmatter.get("id", path.stem),
            created_at=frontmatter.get("created_at", ""),
        )

    def recall(
        self, query: str, categories: list[str] | None = None, limit: int = 5
    ) -> list[MemoryRecord]:
        """Return past records relevant to `query`, ranked by token overlap. This is
        how the organization stops repeating itself: it reads its own failures and
        lessons before it proposes anything new."""
        wanted = _tokens(query)
        if not wanted:
            return []
        scored: list[tuple[int, MemoryRecord]] = []
        for record in self.load_all():
            if categories and record.category not in categories:
                continue
            prov = record.provenance
            searchable = " ".join(
                [
                    record.title,
                    " ".join(record.tags),
                    record.body,
                    str(prov.get("rationale", "")),
                    str(prov.get("rejected_because", "")),
                ]
            )
            overlap = wanted & _tokens(searchable)
            if overlap:
                scored.append((len(overlap), record))
        scored.sort(key=lambda pair: (-pair[0], pair[1].created_at))
        return [record for _, record in scored[:limit]]
