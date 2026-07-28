"""Obsidian vault export for Veritas's own institutional memory.

The second brain — every org's `MemoryStore` plus the cross-org Commons — already
accumulates real, persistent state (see `engine/memory.py`'s own framing: "the only
thing that persists, and the thing that learns"). What it doesn't have is a browsable,
graphable *view* of that accumulation. This mirrors myAIstro's `obsidian_export.py`
one-way rendering: Veritas's SQLite/markdown stores stay canonical, the vault is a
derived, disposable view a human can open in Obsidian to see the org's own memory as
a graph — related records linked, decisions and failures both visible, exactly the
"kept both" design memory.py already commits to.

Default vault path: ~/Documents/veritas-vault
Override with the VERITAS_VAULT_PATH environment variable.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from engine.memory import MemoryRecord, MemoryStore


VAULT_PATH = Path(os.environ.get("VERITAS_VAULT_PATH", "~/Documents/veritas-vault")).expanduser()

# Tags that are structural bookkeeping, not topical signal — excluding them keeps
# "related records" meaningful instead of every accepted artifact linking to every
# other accepted artifact.
_GENERIC_TAGS = {"accepted", "rejected", "decision", "source", "human-vouched"}


def sync_vault(stores: Dict[str, "MemoryStore"], commons: "MemoryStore | None" = None) -> Dict[str, Any]:
    """Re-render every record from every org's memory store (plus Commons, if given)
    into the vault. Cheap enough (small files, dozens-to-hundreds of records) to
    rewrite all on every sync, which keeps "Related records" wikilinks correct."""
    entries: List[tuple[str, "MemoryRecord"]] = []
    for org_name, store in stores.items():
        entries.extend((org_name, r) for r in store.load_all())
    if commons is not None:
        entries.extend(("commons", r) for r in commons.load_all())

    written = export_all(entries)
    return {"vault_path": str(VAULT_PATH), "files_written": len(written)}


def export_all(entries: List[tuple[str, "MemoryRecord"]]) -> List[Path]:
    VAULT_PATH.mkdir(parents=True, exist_ok=True)
    written = [_write_one(org, record, entries) for org, record in entries]

    # Clean up vault files whose record no longer exists (e.g. it was deleted on disk) —
    # without this, a stale .md hangs around and Obsidian's graph shows an orphaned node.
    expected = {p.name for p in written}
    for p in VAULT_PATH.glob("*.md"):
        if p.name not in expected:
            p.unlink()

    return written


def vault_status() -> Dict[str, Any]:
    exists = VAULT_PATH.exists()
    files = sorted(p.name for p in VAULT_PATH.glob("*.md")) if exists else []
    return {"vault_path": str(VAULT_PATH), "exists": exists, "file_count": len(files)}


def _write_one(
    org: str, record: "MemoryRecord", all_entries: List[tuple[str, "MemoryRecord"]]
) -> Path:
    path = VAULT_PATH / _filename_for(org, record)
    path.write_text(_render_markdown(org, record, all_entries), encoding="utf-8")
    return path


def _filename_for(org: str, record: "MemoryRecord") -> str:
    """e.g. 'crypto_hunter - artifact - built a hunt digest (mem_1a2b3c).md' — stable across
    re-exports. The record id is load-bearing, not decoration: two records routinely share
    an identical title (e.g. two "built 'a counter' as a module" decisions from separate
    runs) — without the id, the second export would silently overwrite the first's file."""
    org_part = _sanitize(org)
    cat = _sanitize(record.category or "record")
    title = _sanitize(record.title or record.id)
    return f"{org_part} - {cat} - {title} ({record.id}).md"


def _sanitize(name: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "-", name).strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip("- ") or "untitled"


def _render_markdown(
    org: str, record: "MemoryRecord", all_entries: List[tuple[str, "MemoryRecord"]]
) -> str:
    out: List[str] = []

    out.append("---")
    out.append(f"org: {_yaml_str(org)}")
    out.append(f"category: {_yaml_str(record.category)}")
    out.append(f"id: {_yaml_str(record.id)}")
    out.append(f"created_at: {_yaml_str(record.created_at)}")
    if record.tags:
        out.append("tags:")
        for t in record.tags:
            out.append(f"  - {_yaml_str(t)}")
    out.append("---")
    out.append("")

    out.append(f"# {record.title}")
    out.append("")
    out.append(f"**org:** {org} · **category:** {record.category}")
    out.append("")

    if record.body:
        out.append("## Content")
        out.append("")
        out.append(record.body)
        out.append("")

    reason = record.provenance.get("rejected_because") or record.provenance.get("accepted_because")
    if reason:
        out.append("## Why")
        out.append("")
        out.append(str(reason))
        out.append("")

    informed_by = record.provenance.get("informed_by") or []
    if informed_by:
        out.append("## Informed by")
        out.append("")
        id_to_entry = {r.id: (o, r) for o, r in all_entries}
        for rid in informed_by:
            hit = id_to_entry.get(rid)
            if hit:
                o, r = hit
                target = Path(_filename_for(o, r)).stem
                out.append(f"- [[{target}|{r.title}]]")
            else:
                out.append(f"- (no longer on file: `{rid}`)")
        out.append("")

    related = _find_related(org, record, all_entries)
    if related:
        out.append("## Related records")
        out.append("")
        for o, r, shared in related:
            target = Path(_filename_for(o, r)).stem
            out.append(f"- [[{target}|{r.title}]] — shared: {', '.join(shared[:5])}")
        out.append("")

    return "\n".join(out)


def _find_related(
    org: str, record: "MemoryRecord", all_entries: List[tuple[str, "MemoryRecord"]]
) -> List[tuple[str, "MemoryRecord", List[str]]]:
    """Other records sharing >=1 non-generic tag, ranked by overlap count. Cross-org on
    purpose — a lesson learned in one studio is still relevant context for another."""
    mine = {t.lower() for t in (record.tags or []) if t.lower() not in _GENERIC_TAGS}
    if not mine:
        return []

    matches: List[tuple[str, "MemoryRecord", List[str]]] = []
    for o, other in all_entries:
        if other.id == record.id:
            continue
        theirs = {t.lower() for t in (other.tags or []) if t.lower() not in _GENERIC_TAGS}
        shared = sorted(mine & theirs)
        if shared:
            matches.append((o, other, shared))

    matches.sort(key=lambda m: -len(m[2]))
    return matches[:8]


def _yaml_str(s: object) -> str:
    if s is None:
        return '""'
    s = str(s)
    if not s:
        return '""'
    if re.search(r'[:#\-\[\]{},&*?!|<>=%@`"\']', s) or s.strip() != s:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s
