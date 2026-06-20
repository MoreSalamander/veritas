"""P19 — measurable-aesthetic gates: the hard floor of create mode.

The part of 'taste' that is a fact, checked against a real render: dark/light, contrast, fonts,
palette. A page that meets explicit criteria clears the floor; each mutant trips exactly the
gate that owns its defect. No LLM, no judgment — the create-mode analogue of test_web_studio.
"""

from __future__ import annotations

from engine.artifact import Artifact
from orgs.web_studio.aesthetics import (
    AestheticCriteria,
    ContrastGate,
    FontGate,
    PaletteGate,
    ThemeGate,
    aesthetic_gates,
    normalize_color,
)
from orgs.web_studio.browser import BrowserExecutor

EXEC = BrowserExecutor()

GOOD = ("<!doctype html><html><head><style>"
        "body{background:#0a0a0a;color:#ffffff;font-family:monospace;}"
        "</style></head><body><h1>Title</h1><p>Some readable text.</p></body></html>")
LIGHT = ("<!doctype html><html><head><style>"
         "body{background:#ffffff;color:#000000;font-family:monospace;}"
         "</style></head><body><h1>Title</h1><p>text</p></body></html>")
LOW_CONTRAST = ("<!doctype html><html><head><style>"
                "body{background:#0a0a0a;color:#2a2a2a;font-family:monospace;}"
                "</style></head><body><h1>Title</h1><p>hard to read</p></body></html>")
EXTRA_FONT = GOOD.replace("<p>Some readable text.</p>",
                          "<p>Some readable text.</p><span style=\"font-family:'Comic Sans MS'\">x</span>")
OFF_PALETTE = GOOD.replace("<p>Some readable text.</p>",
                           "<p>Some readable text.</p><span style=\"color:#ff0000\">x</span>")
TINT = GOOD.replace("<p>Some readable text.</p>",
                    "<p>Some readable text.</p><span style=\"color:#f2f2f2\">x</span>")

DARK_THEME = AestheticCriteria(theme="dark", min_contrast=4.5, fonts=["monospace"],
                               palette=["#0a0a0a", "#ffffff"])


def _art() -> Artifact:
    return Artifact.propose(type="page", owner="test", payload="", rationale="test")


def test_normalize_color():
    assert normalize_color("#0A0A0A") == "rgb(10,10,10)"
    assert normalize_color("#fff") == "rgb(255,255,255)"
    assert normalize_color("rgb(10, 20, 30)") == "rgb(10,20,30)"
    assert normalize_color("rgba(10,20,30,0.5)") == "rgb(10,20,30)"


def test_good_page_clears_every_aesthetic_gate():
    rr = EXEC.render(GOOD)
    a = _art()
    gates = aesthetic_gates(rr, DARK_THEME)
    assert [g.name for g in gates] == ["theme", "contrast", "fonts", "palette"]
    assert all(g.check(a).passed for g in gates)


def test_light_page_fails_theme():
    res = ThemeGate(EXEC.render(LIGHT), "dark").check(_art())
    assert not res.passed and "light" in res.evidence


def test_low_contrast_fails_contrast():
    res = ContrastGate(EXEC.render(LOW_CONTRAST), 4.5).check(_art())
    assert not res.passed and "contrast" in res.evidence


def test_off_spec_font_fails_fonts():
    res = FontGate(EXEC.render(EXTRA_FONT), ["monospace"]).check(_art())
    assert not res.passed and "comic sans ms" in res.evidence


def test_off_palette_color_fails_palette():
    res = PaletteGate(EXEC.render(OFF_PALETTE), ["#0a0a0a", "#ffffff"]).check(_art())
    assert not res.passed and "rgb(255,0,0)" in res.evidence


def test_incidental_tint_snaps_to_palette_but_real_color_still_fails():
    # a near-duplicate of an approved color (rendering noise / faint tint) is tolerated...
    assert PaletteGate(EXEC.render(TINT), ["#0a0a0a", "#ffffff"]).check(_art()).passed
    # ...while a genuinely different color is still rejected — the bar is not relaxed, only de-noised
    res = PaletteGate(EXEC.render(OFF_PALETTE), ["#0a0a0a", "#ffffff"]).check(_art())
    assert not res.passed and "rgb(255,0,0)" in res.evidence
