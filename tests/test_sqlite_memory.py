"""P31b — the SQLite-backed institutional memory, the hosting-grade sibling of the filesystem store.

Two things must hold, exactly as for the sandboxed executor. (1) It is genuinely a DIFFERENT BACKEND —
records live in one `.db` file, not a markdown tree, and survive a fresh store reopening the same path.
(2) The VERDICTS ARE UNCHANGED — `recall` is inherited from the base store and built on `load_all`, so an
org ranks its lessons identically whichever backend it reads from. The backend changes where memory
lives; it must never change what the org remembers.
"""

from __future__ import annotations

from engine.memory import (
    TRUST_VOUCHED,
    MemoryRecord,
    MemoryStore,
    SqliteMemoryStore,
    default_memory_store,
)


def _seed(store: MemoryStore) -> None:
    store.persist(MemoryRecord(
        category="failure", title="reverse a string",
        body="off-by-one when reversing", tags=["code", "rejected"],
        provenance={"rejected_because": "dropped the last character"}))
    store.persist(MemoryRecord(
        category="decision", title="built 'a counter' as a module",
        body="Goal: a counter\nChosen shape: module", tags=["decision", "module"]))
    store.persist(MemoryRecord(
        category="artifact", title="add two numbers",
        body="def add(a, b): return a + b", tags=["code", "accepted"]))


# --- it is a real, separate, durable backend --------------------------------------------------

def test_persists_to_a_single_db_file(tmp_path):
    store = SqliteMemoryStore(tmp_path / "m")
    _seed(store)
    assert store.db_path.exists()                       # one file, not a tree
    assert not (tmp_path / "m" / "institutional").exists()  # no markdown directories


def test_records_survive_reopening_the_same_path(tmp_path):
    SqliteMemoryStore(tmp_path / "m").persist(MemoryRecord(
        category="artifact", title="kept", body="durable", tags=["code"]))
    reopened = SqliteMemoryStore(tmp_path / "m")        # a fresh store, same path
    titles = [r.title for r in reopened.load_all()]
    assert titles == ["kept"]


def test_load_all_round_trips_every_field(tmp_path):
    store = SqliteMemoryStore(tmp_path / "m")
    original = MemoryRecord(
        category="failure", title="t", body="b", source_artifact_id="art-1",
        tags=["x", "y"], provenance={"rejected_because": "nope", "n": 3})
    store.persist(original)
    got = store.load_all()[0]
    assert (got.category, got.title, got.body, got.source_artifact_id, got.tags, got.provenance) == (
        "failure", "t", "b", "art-1", ["x", "y"], {"rejected_because": "nope", "n": 3})


# --- THE INVARIANT: the backend does not change what the org recalls --------------------------

def test_recall_matches_the_filesystem_store(tmp_path):
    fs, db = MemoryStore(tmp_path / "fs"), SqliteMemoryStore(tmp_path / "db")
    _seed(fs)
    _seed(db)
    for query in ["reverse a string", "build a counter module", "add numbers", "unrelated quantum"]:
        fs_titles = [r.title for r in fs.recall(query)]
        db_titles = [r.title for r in db.recall(query)]
        assert fs_titles == db_titles  # same lessons surface, in the same order


# --- containment and isolation carry over -----------------------------------------------------

def test_source_containment_is_enforced(tmp_path):
    store = SqliteMemoryStore(tmp_path / "m")
    bare = MemoryRecord(category="source", title="s", body="transcript", tags=["source"])
    try:
        store.persist(bare)
        assert False, "an unlabeled source record must be refused"
    except ValueError:
        pass
    ok = MemoryRecord(category="source", title="s", body="transcript",
                      tags=["source", TRUST_VOUCHED],
                      provenance={"url": "https://x", "trust": TRUST_VOUCHED})
    store.persist(ok)  # labeled + sourced: allowed
    assert [r.title for r in store.load_all()] == ["s"]


def test_two_tenants_cannot_see_each_others_memory(tmp_path):
    a = SqliteMemoryStore(tmp_path / "tenant_a")
    b = SqliteMemoryStore(tmp_path / "tenant_b")
    a.persist(MemoryRecord(category="artifact", title="a-secret", body="x", tags=["code"]))
    assert [r.title for r in a.load_all()] == ["a-secret"]
    assert b.load_all() == []  # separate path -> separate db -> no cross-tenant read


# --- the one swap point -----------------------------------------------------------------------

def test_factory_selects_backend_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VERITAS_MEMORY", "sqlite")
    assert isinstance(default_memory_store(tmp_path / "a"), SqliteMemoryStore)
    monkeypatch.delenv("VERITAS_MEMORY", raising=False)
    assert isinstance(default_memory_store(tmp_path / "b"), MemoryStore)
    assert not isinstance(default_memory_store(tmp_path / "c"), SqliteMemoryStore)
