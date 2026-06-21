"""Memory frontmatter must survive '---' inside values.

A model can write anything into a title or rationale — including "---" (e.g. "PROTOCOL --- a
thriller"). The frontmatter parser must end the block at a delimiter *line*, never at a '---'
buried in a value, and a malformed record must never crash the org reading its own memory.
"""

from __future__ import annotations

from engine.memory import MemoryRecord, MemoryStore


def test_triple_dash_inside_values_round_trips(tmp_path):
    store = MemoryStore(tmp_path)
    rec = MemoryRecord(
        category="artifact",
        title="THE NOT IT PROTOCOL --- a dark thriller",
        body="a concept with: descriptions, and visual style notes.\n\nmore --- text in the body.",
        tags=["concept"],
        provenance={"rationale": "concept for: THE NOT IT PROTOCOL --- noir", "created_by": "x"},
    )
    store.persist(rec)
    back = store.load_all()
    assert len(back) == 1
    assert back[0].title == rec.title
    assert back[0].provenance["rationale"] == rec.provenance["rationale"]
    assert back[0].body == rec.body


def test_a_corrupt_record_does_not_crash_load(tmp_path):
    store = MemoryStore(tmp_path)
    store.persist(MemoryRecord(category="artifact", title="good", body="ok"))
    # a hand-corrupted frontmatter (unterminated quote) must degrade, not raise
    (store.institutional / "bad.md").write_text('---\ntitle: "oops\n---\n\nbody\n', encoding="utf-8")
    records = store.load_all()  # must not raise
    assert any(r.title == "good" for r in records)
