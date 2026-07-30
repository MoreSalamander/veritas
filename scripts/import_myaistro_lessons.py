#!/usr/bin/env python
"""Import myAIstro's authored lessons into Veritas's Second Brain (the commons).

myAIstro is the user's own lesson → SOT → Obsidian-graph system (a separate project,
~/myAIstro). This script bridges the two WITHOUT merging them — myAIstro stays canonical for its
own domain, and its lessons enter Veritas as `source` records: human-vouched material any org's
grounding gate may cite (`"Source X states Y"`), never treated as a verified fact on arrival. The
lesson's own `validation_score` (myAIstro's own summarization-quality check) is carried as
provenance context, NOT a trust upgrade — it is model-judged quality, not a Veritas hard gate, so
promoting it to "verified" here would be exactly the overclaim this system exists to refuse.

Reuses myAIstro's OWN rendering code (`core.obsidian_export`) rather than re-implementing it, so
the commons record's content is byte-identical to the real, materialized Obsidian vault file — one
source of truth, no drift. Each lesson is tagged with its course + key concepts so Veritas's own
vault re-export (`engine/memory_export.py`, already in this repo) can surface real cross-org
relationship links, not inert blobs.

Known limitation (by design, for this first pass): NOT idempotent. Re-running duplicates every
lesson as a new commons record (each gets a fresh id). A production version would upsert on
myAIstro's own `event_id`. Fine for a one-time import; flagged here on purpose.

Usage:  .venv/bin/python scripts/import_myaistro_lessons.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MYAISTRO_BACKEND = Path("~/myAIstro/backend").expanduser()
SOT_FILE = MYAISTRO_BACKEND / "memory_store.json"

sys.path.insert(0, str(MYAISTRO_BACKEND))

from engine.memory import MemoryRecord, default_memory_store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report what would be imported, write nothing")
    args = ap.parse_args()

    if not SOT_FILE.exists():
        sys.exit(f"myAIstro SOT not found at {SOT_FILE} — is ~/myAIstro checked out at the expected path?")

    from core.obsidian_export import export_all  # myAIstro's own renderer — reused, not duplicated

    entries = json.loads(SOT_FILE.read_text())
    if not entries:
        sys.exit("myAIstro SOT is empty — nothing to import.")

    print(f"loaded {len(entries)} lesson(s) from {SOT_FILE}")
    written_paths = export_all(entries)  # materializes the real myAIstro Obsidian vault on disk
    print(f"materialized {len(written_paths)} vault file(s) at "
          f"{written_paths[0].parent if written_paths else '(none)'}")

    commons = default_memory_store(ROOT / "hub_data" / "memory" / "commons")

    imported = 0
    for entry, path in zip(entries, written_paths):
        course = entry.get("course") or ""
        lesson = entry.get("lesson") or path.stem
        key_concepts = entry.get("key_concepts") or []
        score = entry.get("validation_score", 0)

        rec = MemoryRecord.from_source(
            url=f"file://{path.resolve()}",
            transcript=path.read_text(encoding="utf-8"),
            channel=course,
            title=lesson,
            captured_why=(
                f"Authored myAIstro lesson (validation_score={score}). "
                f"Key concepts: {', '.join(key_concepts) or '(none recorded)'}."
            ),
        )
        # Extra tags beyond from_source's default ["source", "human-vouched"] — these are what let
        # Veritas's own vault re-export find REAL cross-org relationships (memory_export.py matches
        # on non-generic tags), instead of every myAIstro lesson looking unrelated to everything else.
        if course:
            rec.tags.append(course.lower())
        rec.tags.extend(kc.lower() for kc in key_concepts)

        if args.dry_run:
            print(f"  [dry-run] would import: {lesson!r} (course={course!r}, tags={rec.tags})")
            continue
        commons.persist(rec)
        imported += 1

    if args.dry_run:
        print(f"\ndry run complete — {len(written_paths)} lesson(s) would be imported. Nothing written.")
    else:
        print(f"\nimported {imported} lesson(s) into Veritas's commons at {commons.base}")
        print("run the hub's own vault sync (POST /api/memory/sync-vault or engine/memory_export.sync_vault)"
              " to see them in Veritas's browsable Obsidian graph too.")


if __name__ == "__main__":
    main()
