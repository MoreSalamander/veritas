"""hub/commons_search.py — offline, deterministic. ScriptedSearchClient stands in for a live
Parallel call throughout; the trust decision (every persisted record is machine-fetched, never
human-vouched) is the thing actually under test here, not the network.
"""

from __future__ import annotations

from pathlib import Path

from engine.memory import TRUST_MACHINE_FETCHED, MemoryStore
from commons.search import search_and_ingest
from commons.parallel_client import ExtractResult, ScriptedSearchClient, SearchResult


def test_search_and_ingest_persists_each_extracted_result_as_machine_fetched(tmp_path):
    client = ScriptedSearchClient(
        search_by_query={
            "ls bellhousing pattern": [
                SearchResult(url="https://a.com", title="A"),
                SearchResult(url="https://b.com", title="B"),
            ],
        },
        extract_by_url={
            "https://a.com": ExtractResult(url="https://a.com", title="A", content="content a"),
            "https://b.com": ExtractResult(url="https://b.com", title="B", content="content b"),
        },
    )
    commons = MemoryStore(tmp_path / "commons")
    persisted = search_and_ingest("ls bellhousing pattern", client, commons)

    assert len(persisted) == 2
    assert {r.provenance["url"] for r in persisted} == {"https://a.com", "https://b.com"}
    for r in persisted:
        assert r.provenance["trust"] == TRUST_MACHINE_FETCHED
        assert r.provenance["search_query"] == "ls bellhousing pattern"

    # And it's really durable, not just returned — reload from disk.
    reloaded = commons.load_all()
    assert len(reloaded) == 2


def test_search_and_ingest_skips_a_result_that_fails_to_extract_without_failing_the_whole_call(tmp_path):
    # https://b.com is NOT in extract_by_url, so ScriptedSearchClient.extract raises for it —
    # search_and_ingest must swallow that one and still persist a.com.
    client = ScriptedSearchClient(
        search_by_query={
            "q": [SearchResult(url="https://a.com"), SearchResult(url="https://b.com")],
        },
        extract_by_url={"https://a.com": ExtractResult(url="https://a.com", content="good")},
    )
    commons = MemoryStore(tmp_path / "commons")
    persisted = search_and_ingest("q", client, commons)

    assert len(persisted) == 1
    assert persisted[0].provenance["url"] == "https://a.com"


def test_search_and_ingest_with_no_search_results_persists_nothing(tmp_path):
    client = ScriptedSearchClient()  # no scripted results for any query
    commons = MemoryStore(tmp_path / "commons")
    assert search_and_ingest("nothing findable", client, commons) == []
    assert commons.load_all() == []


def test_search_and_ingest_respects_max_results(tmp_path):
    client = ScriptedSearchClient(
        search_by_query={"q": [
            SearchResult(url=f"https://{i}.com") for i in range(5)
        ]},
        extract_by_url={
            f"https://{i}.com": ExtractResult(url=f"https://{i}.com", content=f"c{i}")
            for i in range(5)
        },
    )
    commons = MemoryStore(tmp_path / "commons")
    persisted = search_and_ingest("q", client, commons, max_results=2)
    assert len(persisted) == 2
