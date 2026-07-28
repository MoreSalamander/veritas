"""engine/grounding.py — the second-brain-specific check: does a MemoryRecord's own
`informed_by` trail actually hold up against the records it claims informed it."""

from __future__ import annotations

from engine.grounding import (
    check_code_grounding,
    check_text_grounding,
    combined_report,
    record_grounding,
)
from engine.memory import MemoryRecord, MemoryStore


# --- pure text/code checks (same shape as myAIstro's, adapted) --------------------

def test_text_grounding_empty_text_is_trivially_grounded():
    assert check_text_grounding("", "anything") == {
        "kind": "text", "total_tokens": 0, "grounded_tokens": 0,
        "ratio": 1.0, "ungrounded_sample": [],
    }


def test_text_grounding_no_source_is_fully_ungrounded():
    r = check_text_grounding("substantial words here", "")
    assert r["ratio"] == 0.0
    assert r["total_tokens"] > 0


def test_text_grounding_full_overlap():
    r = check_text_grounding("hallucination detection matters", "hallucination detection matters a lot")
    assert r["ratio"] == 1.0


def test_text_grounding_partial_overlap_reports_ungrounded_sample():
    r = check_text_grounding("reverse strings fabricated claim", "reverse strings implementation")
    assert 0.0 < r["ratio"] < 1.0
    assert "fabricated" in r["ungrounded_sample"] or "claim" in r["ungrounded_sample"]


def test_code_grounding_inline_snippet_matches_verbatim():
    r = check_code_grounding("uses `def add(a, b): return a + b`", "def add(a, b): return a + b")
    assert r["ratio"] == 1.0


def test_code_grounding_fenced_block_partial_line_match():
    text = "```\ndef add(a, b):\n    return a + b\n```"
    source = "def add(a, b):\n    return a - b"  # second line drifted
    r = check_code_grounding(text, source)
    assert r["grounded_snippets"] == 1  # half the lines matched -> counts as grounded


def test_code_grounding_no_snippets_is_trivially_grounded():
    assert check_code_grounding("plain prose, no code", "anything")["ratio"] == 1.0


def test_combined_report_weights_text_and_code():
    r = combined_report("hallucination `def f(): pass`", "hallucination def f(): pass")
    assert r["overall_ratio"] == 1.0


# --- record_grounding: the memory-trail check ---------------------------------------

def test_record_with_no_informed_by_has_no_grounding_report(tmp_path):
    store = MemoryStore(tmp_path / "m")
    record = MemoryRecord(category="artifact", title="standalone", body="no trail")
    assert record_grounding(record, store) is None


def test_record_grounded_in_its_declared_source(tmp_path):
    store = MemoryStore(tmp_path / "m")
    source = MemoryRecord(category="decision", title="prior decision",
                           body="built a reverse-string function using a slice")
    store.persist(source)
    record = MemoryRecord(
        category="artifact", title="follow-up", body="used a slice to reverse the string",
        provenance={"informed_by": [source.id]},
    )
    report = record_grounding(record, store)
    assert report is not None
    assert report["overall_ratio"] > 0.5


def test_record_ungrounded_against_a_source_it_doesnt_match(tmp_path):
    store = MemoryStore(tmp_path / "m")
    source = MemoryRecord(category="decision", title="unrelated", body="painted the fence blue")
    store.persist(source)
    record = MemoryRecord(
        category="artifact", title="drifted", body="implemented quicksort recursively",
        provenance={"informed_by": [source.id]},
    )
    report = record_grounding(record, store)
    assert report is not None
    assert report["overall_ratio"] < 0.5


def test_record_with_missing_informed_by_source_flags_it_honestly(tmp_path):
    store = MemoryStore(tmp_path / "m")
    record = MemoryRecord(
        category="artifact", title="dangling", body="claims a trail that's gone",
        provenance={"informed_by": ["mem-does-not-exist"]},
    )
    report = record_grounding(record, store)
    assert report is not None
    assert report["missing_sources"] == ["mem-does-not-exist"]
    assert report["text"]["ratio"] == 0.0  # no source at all -> nothing can be grounded
