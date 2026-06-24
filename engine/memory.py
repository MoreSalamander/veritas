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
from engine.embed import Embedder, cosine

# Deterministic retrieval: overlap of meaningful tokens. Explainable and testable.
# An embedding-backed recall can slot in behind the same interface later.
_STOPWORDS = {
    "a", "an", "the", "of", "to", "and", "or", "that", "this", "returns", "return",
    "function", "func", "def", "is", "are", "for", "with", "in", "on", "be", "given",
    "value", "values", "number", "numbers", "integer", "string",
}


# The third trust tier as it appears in the commons: the human curated this source. It vouches
# for the source's worth, never for the truth of the claims inside it (see from_source). P28.
TRUST_VOUCHED = "human-vouched"


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
    """Turn recalled memory into a prompt preamble. Failures/lessons warn the proposer off
    past mistakes; decisions tell it how the org structured similar goals before (so new
    work stays consistent). Org-agnostic."""
    if not recalled:
        return None
    failures = [r for r in recalled if r.category != "decision"]
    decisions = [r for r in recalled if r.category == "decision"]
    blocks: list[str] = []
    if failures:
        lines = ["Lessons from past attempts at similar goals (avoid repeating these):"]
        for r in failures:
            reason = r.provenance.get("rejected_because")
            if not reason:
                reason = r.body.splitlines()[0] if r.body else r.title
            lines.append(f"- {r.title}: {reason}")
        blocks.append("\n".join(lines))
    if decisions:
        lines = ["How the org structured similar goals before (prefer consistency):"]
        for r in decisions:
            lines.append(f"- {r.title}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else None


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
    def from_decision(
        cls, *, goal: str, shape: str, artifact_types: list[str], source_ids: list[str]
    ) -> "MemoryRecord":
        """A factual record of what the org decided and shipped — the Memory seat. Not an
        LLM proposal: it's built deterministically from an accepted build, so it's complete
        and explainable by construction (Rule 4)."""
        return cls(
            category="decision",
            title=f"built {goal!r} as a {shape}",
            body=(
                f"Goal: {goal}\nChosen shape: {shape}\n"
                f"Produced: {', '.join(artifact_types)}\nShipped — verified by the org's gates."
            ),
            tags=["decision", shape],
            provenance={"goal": goal, "shape": shape, "artifacts": list(source_ids)},
        )

    @classmethod
    def from_source(
        cls,
        *,
        url: str,
        transcript: str,
        captured_why: str = "",
        channel: str = "",
        title: str | None = None,
    ) -> "MemoryRecord":
        """A piece of curated source material entering the commons (the Second Brain).

        The human picked it, so it is `human-vouched` — but that vouches for the SOURCE, not the
        truth of its claims (the human did not fact-check every sentence; they often hadn't even
        read the transcript when they shared it). So this is NOT a verified artifact: a consumer
        may cite it as "Source X states Y" (attributed — the quote is verbatim, the source vouched)
        but may never ground "Y is true" on it. The `trust: human-vouched` provenance and the tag
        below carry that contract; `persist` refuses any source record that drops them (P28a)."""
        if not (url and url.strip()):
            raise ValueError("a source record needs a resolvable origin (url)")
        return cls(
            category="source",
            title=title or (f"[source] {channel}" if channel else f"[source] {url}"),
            body=transcript,
            tags=["source", TRUST_VOUCHED],
            provenance={
                "url": url,
                "channel": channel,
                "captured_why": captured_why,
                "trust": TRUST_VOUCHED,
            },
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

    def __init__(self, base_path: Path | str, embedder: Embedder | None = None) -> None:
        self.base = Path(base_path)
        self.institutional = self.base / "institutional"
        self.failures = self.base / "failures"
        self.index_path = self.base / "index.md"
        self.institutional.mkdir(parents=True, exist_ok=True)
        self.failures.mkdir(parents=True, exist_ok=True)
        # When set, recall ranks by semantic similarity instead of token overlap (P23).
        self.embedder = embedder
        self._embed_cache: dict[str, list[float]] = {}

    def persist(self, record: MemoryRecord) -> Path:
        # Containment (P28): a source record without a resolvable origin AND the human-vouched
        # trust tag is refused — unverified material may live in the commons only while it stays
        # labeled, so nothing downstream can mistake it for a fact.
        if record.category == "source":
            if not record.provenance.get("url"):
                raise ValueError("a source record needs a resolvable origin to persist")
            if record.provenance.get("trust") != TRUST_VOUCHED or TRUST_VOUCHED not in record.tags:
                raise ValueError("a source record must carry the human-vouched trust tag to persist")
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
            # The frontmatter block ends at the first *line* that is exactly '---'. A naive
            # text.split('---') broke whenever a value contained '---' (e.g. a model wrote
            # "PROTOCOL --- a thriller"), cutting the YAML mid-value. Match the delimiter by line.
            lines = text.split("\n")
            end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
            if end is not None:
                try:
                    loaded = yaml.safe_load("\n".join(lines[1:end]))
                except yaml.YAMLError:
                    loaded = None  # a malformed record must never crash the org reading its memory
                if isinstance(loaded, dict):
                    frontmatter = loaded
                    body = "\n".join(lines[end + 1:]).strip()
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

    def _searchable(self, record: MemoryRecord) -> str:
        prov = record.provenance
        return " ".join([
            record.title, " ".join(record.tags), record.body,
            str(prov.get("rationale", "")), str(prov.get("rejected_because", "")),
        ])

    def recall(
        self, query: str, categories: list[str] | None = None, limit: int = 5,
        min_similarity: float = 0.5,
    ) -> list[MemoryRecord]:
        """Return past records relevant to `query`. With an embedder set, ranks by SEMANTIC
        similarity (catches a lesson even when the wording differs); otherwise by token overlap.
        Either way: how the organization stops repeating itself — it reads its own failures and
        lessons before it proposes anything new."""
        candidates = [
            r for r in self.load_all() if not categories or r.category in categories
        ]
        if not candidates:
            return []

        if self.embedder is not None:
            try:
                q = self.embedder.embed(query)
            except Exception:
                q = []
            if q:
                scored: list[tuple[float, MemoryRecord]] = []
                for record in candidates:
                    vec = self._embed_record(record)
                    if vec:
                        scored.append((cosine(q, vec), record))
                scored.sort(key=lambda pair: (-pair[0], pair[1].created_at))
                return [r for sim, r in scored[:limit] if sim >= min_similarity]
            # embedding failed (e.g. Ollama down) — fall through to token overlap

        wanted = _tokens(query)
        if not wanted:
            return []
        overlapped: list[tuple[int, MemoryRecord]] = []
        for record in candidates:
            overlap = wanted & _tokens(self._searchable(record))
            if overlap:
                overlapped.append((len(overlap), record))
        overlapped.sort(key=lambda pair: (-pair[0], pair[1].created_at))
        return [record for _, record in overlapped[:limit]]

    def _embed_record(self, record: MemoryRecord) -> list[float]:
        if record.id not in self._embed_cache and self.embedder is not None:
            try:
                self._embed_cache[record.id] = self.embedder.embed(self._searchable(record))
            except Exception:
                self._embed_cache[record.id] = []
        return self._embed_cache.get(record.id, [])
