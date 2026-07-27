"""The orchestrator: read -> structural gate -> admit-or-hold -> persist.

Per-source isolation mirrors opportunity-agency-ai's own gather_all: one
broken source (an unknown kind, a reader raising) must never take down
collection for every other configured source.
"""

from __future__ import annotations

from .gate import check_structural
from .readers import KIND_READERS
from .records import AdmissionState
from .sources import SourceConfig
from .store import CollectorStore


def collect_one(cfg: SourceConfig, store: CollectorStore) -> int:
    reader = KIND_READERS.get(cfg.kind)
    if reader is None:
        print(f"[collector] unknown kind {cfg.kind!r} for source {cfg.name!r} — skipping")
        return 0
    try:
        records = reader(cfg)
    except Exception as exc:  # noqa: BLE001 — any reader failure must not kill the run
        print(f"[collector] failed to read source {cfg.name!r}: {exc}")
        return 0

    for rec in records:
        verdict = check_structural(rec)
        if verdict.passed and cfg.default_trust == "auto":
            rec.admitted = True
            rec.admitted_by = "auto:structural-check"
            rec.admitted_at = rec.collected_at
            rec.state = AdmissionState.ADMITTED
        elif not verdict.passed:
            print(f"[collector] {cfg.name!r} record {rec.source_ref!r} failed the structural"
                  f" gate ({verdict.reason}) — collected as pending, not auto-admitted")
        # else: passed but this source isn't auto-trusted yet — stays pending,
        # collected as honest bookkeeping until a human decides.
        store.upsert(rec)
    return len(records)


def run_collection(sources: dict[str, SourceConfig], store: CollectorStore) -> dict[str, int]:
    """{source_name: count}, every configured source appears even at 0 —
    same shape as opportunity-agency-ai's gather_all."""
    return {name: collect_one(cfg, store) for name, cfg in sources.items()}
