"""P30c — the report aggregation, offline (the real model run is in bench/run_trust.py main)."""

from __future__ import annotations

from bench.trust_bench import BatteryResult, Report, Verdict
from bench.run_trust import format_markdown, summarize


def _result(rows: list[tuple[Verdict, Verdict, bool]]) -> BatteryResult:
    """rows = [(bare_verdict, veritas_verdict, catchable), ...]"""
    bare, ver = Report("bare-agent"), Report("veritas")
    records = []
    for bv, vv, c in rows:
        bare.add(bv)
        ver.add(vv)
        records.append(("task", c, bv, vv))
    return BatteryResult(bare, ver, records)


def test_summary_captures_the_headline_and_reproducibility():
    # two repeats: bare false-ships the one catchable-wrong task, Veritas refuses it; one easy task both
    # ship correct; one uncatchable both false-ship.
    rows = [
        (Verdict.SHIPPED_WRONG, Verdict.REFUSED_GOOD, True),     # catchable
        (Verdict.SHIPPED_CORRECT, Verdict.SHIPPED_CORRECT, True),  # easy
        (Verdict.SHIPPED_WRONG, Verdict.SHIPPED_WRONG, False),    # uncatchable (honest limit)
    ]
    s = summarize("demo", [_result(rows), _result(rows)])
    assert s.repeats == 2
    assert s.catchable_bare_false == 1.0 and s.catchable_veritas_false == 0.0  # the win
    assert s.veritas_over_refusal == 0.0
    assert s.bare_false_ship == 2 / 3 and s.veritas_false_ship == 1 / 3
    assert s.reproducible is True


def test_reproducible_is_false_when_a_repeat_breaks_the_finding():
    good = [(Verdict.SHIPPED_WRONG, Verdict.REFUSED_GOOD, True)]
    bad = [(Verdict.SHIPPED_CORRECT, Verdict.SHIPPED_WRONG, True)]  # Veritas false-ships MORE than bare
    s = summarize("flaky", [_result(good), _result(bad)])
    assert s.reproducible is False


def test_markdown_table_renders():
    s = summarize("demo", [_result([(Verdict.SHIPPED_WRONG, Verdict.REFUSED_GOOD, True)])])
    md = format_markdown([s])
    assert "Trust benchmark" in md and "catchable false-ships" in md
    assert "| demo |" in md and "yes" in md
