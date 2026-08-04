"""Turns a live web search into new Knowledge Graph sources — the orchestration layer over
hub/parallel_client.py's pure fetch seam. This is where the trust DECISION actually happens: every
result persisted here is tagged machine-fetched (engine/memory.py's `TRUST_MACHINE_FETCHED`), never
laundered into looking human-vouched no matter how good the source turns out to be. Kept separate
from parallel_client.py on purpose — that module only fetches; this one decides what a fetch is
worth and commits it to memory.
"""

from __future__ import annotations

from engine.memory import MemoryRecord, MemoryStore
from hub.parallel_client import ParallelUnavailable, SearchClient


def search_and_ingest(
    query: str, client: SearchClient, commons: MemoryStore, max_results: int = 3,
) -> list[MemoryRecord]:
    """Search the open web for `query`, extract the top results, and persist each as a
    machine-fetched commons source. A single URL failing to extract (blocked, dead, empty) is
    skipped, not fatal for the whole call — a partial haul is a legitimate, honest outcome, the
    same "one bad item doesn't sink the run" discipline this codebase uses everywhere else.
    Returns only what was actually persisted, so an empty list means exactly what it says: nothing
    usable was found, not a hidden partial failure."""
    persisted: list[MemoryRecord] = []
    for result in client.search(query, max_results=max_results):
        try:
            extracted = client.extract(result.url, objective=query)
        except ParallelUnavailable:
            continue  # this one candidate failed to extract; the rest still get a chance
        record = MemoryRecord.from_machine_fetched_source(
            url=extracted.url,
            content=extracted.content,
            search_query=query,
            channel=extracted.title,
            title=extracted.title or None,
        )
        commons.persist(record)
        persisted.append(record)
    return persisted
