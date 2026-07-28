"""engine/memory_export.py — the Obsidian vault export of Veritas's own institutional
memory. One-way: the memory stores stay canonical, the vault is a derived view."""

from __future__ import annotations

import engine.memory_export as memory_export
from engine.memory import MemoryRecord, MemoryStore


def _patch_vault_path(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    monkeypatch.setattr(memory_export, "VAULT_PATH", vault)
    return vault


def test_sync_vault_writes_one_file_per_record(tmp_path, monkeypatch):
    vault = _patch_vault_path(monkeypatch, tmp_path)
    store = MemoryStore(tmp_path / "m" / "software")
    store.persist(MemoryRecord(category="artifact", title="add two numbers", body="def add(a,b): return a+b"))
    store.persist(MemoryRecord(category="failure", title="broken reverse", body="off by one"))

    result = memory_export.sync_vault({"software": store})

    assert result["files_written"] == 2
    assert vault.exists()
    assert len(list(vault.glob("*.md"))) == 2


def test_sync_vault_includes_commons_when_given(tmp_path, monkeypatch):
    _patch_vault_path(monkeypatch, tmp_path)
    org_store = MemoryStore(tmp_path / "m" / "web")
    commons = MemoryStore(tmp_path / "m" / "commons")
    commons.persist(MemoryRecord.from_source(url="https://example.com/x", transcript="a talk"))

    result = memory_export.sync_vault({"web": org_store}, commons=commons)

    assert result["files_written"] == 1
    files = list(memory_export.VAULT_PATH.glob("*.md"))
    assert any("commons" in f.name for f in files)


def test_export_cleans_up_deleted_records(tmp_path, monkeypatch):
    vault = _patch_vault_path(monkeypatch, tmp_path)
    store = MemoryStore(tmp_path / "m" / "software")
    r = MemoryRecord(category="artifact", title="temp", body="temp body")
    store.persist(r)
    memory_export.sync_vault({"software": store})
    assert len(list(vault.glob("*.md"))) == 1

    # Record no longer on disk -> the stale vault file must be removed on next sync.
    (store.institutional / f"{r.id}.md").unlink()
    memory_export.sync_vault({"software": store})
    assert len(list(vault.glob("*.md"))) == 0


def test_related_records_linked_by_shared_non_generic_tags(tmp_path, monkeypatch):
    _patch_vault_path(monkeypatch, tmp_path)
    store = MemoryStore(tmp_path / "m" / "software")
    a = MemoryRecord(category="artifact", title="first module", body="x", tags=["module", "accepted"])
    b = MemoryRecord(category="artifact", title="second module", body="y", tags=["module", "accepted"])
    store.persist(a)
    store.persist(b)
    memory_export.sync_vault({"software": store})

    rendered = (memory_export.VAULT_PATH / memory_export._filename_for("software", a)).read_text()
    assert "Related records" in rendered
    assert "second module" in rendered


def test_generic_tags_alone_dont_count_as_related(tmp_path, monkeypatch):
    _patch_vault_path(monkeypatch, tmp_path)
    store = MemoryStore(tmp_path / "m" / "software")
    a = MemoryRecord(category="artifact", title="a", body="x", tags=["accepted"])
    b = MemoryRecord(category="artifact", title="b", body="y", tags=["accepted"])
    store.persist(a)
    store.persist(b)
    memory_export.sync_vault({"software": store})

    rendered = (memory_export.VAULT_PATH / memory_export._filename_for("software", a)).read_text()
    assert "Related records" not in rendered


def test_informed_by_renders_as_wikilink_when_source_still_on_file(tmp_path, monkeypatch):
    _patch_vault_path(monkeypatch, tmp_path)
    store = MemoryStore(tmp_path / "m" / "software")
    source = MemoryRecord(category="decision", title="prior decision", body="x")
    store.persist(source)
    record = MemoryRecord(category="artifact", title="follow-up", body="y",
                           provenance={"informed_by": [source.id]})
    store.persist(record)
    memory_export.sync_vault({"software": store})

    rendered = (memory_export.VAULT_PATH / memory_export._filename_for("software", record)).read_text()
    assert "Informed by" in rendered
    assert "prior decision" in rendered


def test_records_with_identical_titles_dont_collide_on_disk(tmp_path, monkeypatch):
    # Regression: two records sharing a title (routine — e.g. two runs both "built
    # 'a counter' as a module") must not overwrite each other in the vault.
    vault = _patch_vault_path(monkeypatch, tmp_path)
    store = MemoryStore(tmp_path / "m" / "software")
    store.persist(MemoryRecord(category="decision", title="built 'a counter' as a module", body="run one"))
    store.persist(MemoryRecord(category="decision", title="built 'a counter' as a module", body="run two"))

    result = memory_export.sync_vault({"software": store})

    assert result["files_written"] == 2
    assert len(list(vault.glob("*.md"))) == 2


def test_vault_status_reports_not_synced_before_any_sync(tmp_path, monkeypatch):
    _patch_vault_path(monkeypatch, tmp_path)
    status = memory_export.vault_status()
    assert status["exists"] is False
    assert status["file_count"] == 0
