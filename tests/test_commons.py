"""The Knowledge Graph — the cross-org knowledge commons (P28a).

The commons is an ordinary MemoryStore rooted at its own folder, holding curated source material
under category="source". Its verification model is CONTAINMENT, not content: a source record may
live here only while it stays labeled with a recognized trust tag (`human-vouched` — a person
curated it — or `machine-fetched` — Veritas found and fetched it itself, e.g. via Parallel; see
P28c) and a resolvable origin. The store refuses any source record that drops either — so nothing
downstream can mistake unverified material for a fact. And because every org's recall() filters
categories to failure/lesson/decision, a source record never leaks into an org's run unless that
org explicitly opts in (P28c).
"""

from __future__ import annotations

import pytest

from engine.memory import TRUST_MACHINE_FETCHED, TRUST_VOUCHED, MemoryRecord, MemoryStore


def test_curated_source_persists_with_full_provenance(tmp_path):
    commons = MemoryStore(tmp_path / "commons")
    rec = MemoryRecord.from_source(
        url="https://youtu.be/abc123",
        channel="Some Lecturer",
        transcript="In this talk I argue that the gravitational constant is roughly 6.674e-11.",
        captured_why="might inform the physics research org",
    )
    commons.persist(rec)

    back = commons.load_all()
    assert len(back) == 1
    got = back[0]
    assert got.category == "source"
    assert got.provenance["url"] == "https://youtu.be/abc123"
    assert got.provenance["trust"] == TRUST_VOUCHED
    assert got.provenance["captured_why"] == "might inform the physics research org"
    assert TRUST_VOUCHED in got.tags
    assert "gravitational constant" in got.body


def test_source_without_origin_is_rejected():
    with pytest.raises(ValueError):
        MemoryRecord.from_source(url="", transcript="orphaned material")


def test_source_stripped_of_trust_tag_is_refused_at_persist(tmp_path):
    commons = MemoryStore(tmp_path / "commons")
    rec = MemoryRecord.from_source(url="https://youtu.be/abc123", transcript="text")
    # Simulate tampering: someone strips the containment label before persisting.
    rec.provenance.pop("trust")
    rec.tags = [t for t in rec.tags if t != TRUST_VOUCHED]
    with pytest.raises(ValueError):
        commons.persist(rec)


def test_machine_fetched_source_persists_with_its_own_trust_tag(tmp_path):
    commons = MemoryStore(tmp_path / "commons")
    rec = MemoryRecord.from_machine_fetched_source(
        url="https://example.com/bellhousing-patterns",
        content="The LS-family bellhousing pattern differs from the SBC pattern.",
        search_query="LS bellhousing pattern vs SBC",
        channel="example.com",
    )
    commons.persist(rec)

    got = commons.load_all()[0]
    assert got.provenance["trust"] == TRUST_MACHINE_FETCHED
    assert TRUST_MACHINE_FETCHED in got.tags
    assert got.provenance["search_query"] == "LS bellhousing pattern vs SBC"
    # Distinct tier, not a human-vouched record wearing a different label.
    assert TRUST_VOUCHED not in got.tags


def test_machine_fetched_source_without_origin_is_rejected():
    with pytest.raises(ValueError):
        MemoryRecord.from_machine_fetched_source(url="", content="x", search_query="q")


def test_human_vouched_and_machine_fetched_are_not_interchangeable(tmp_path):
    # A caller can't launder a machine-fetched record by mislabeling it human-vouched, or vice
    # versa — persist() checks that provenance["trust"] and the tag AGREE, not just that either
    # is a recognized tier.
    commons = MemoryStore(tmp_path / "commons")
    rec = MemoryRecord.from_machine_fetched_source(
        url="https://example.com/x", content="y", search_query="q",
    )
    rec.provenance["trust"] = TRUST_VOUCHED  # tamper: claim human-vouched in provenance...
    # ...but the tag still says machine-fetched — persist must catch the mismatch either way.
    with pytest.raises(ValueError):
        commons.persist(rec)


def test_source_records_do_not_leak_into_an_orgs_default_recall(tmp_path):
    # An org reads its own memory filtered to failure/lesson/decision; commons sources must not
    # appear there. (They share no folder anyway, but prove the category filter is the guard.)
    commons = MemoryStore(tmp_path / "commons")
    commons.persist(
        MemoryRecord.from_source(
            url="https://youtu.be/xyz", transcript="encode then decode round trips cleanly"
        )
    )
    leaked = commons.recall("round trip encode decode", categories=["failure", "lesson", "decision"])
    assert leaked == []
    # but it IS findable when a consumer explicitly asks for source material (P28c)
    found = commons.recall("round trip encode decode", categories=["source"])
    assert len(found) == 1
