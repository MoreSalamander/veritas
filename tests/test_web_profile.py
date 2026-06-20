"""P22 — the aesthetic profile: the loop compounds (it learns your taste).

Each human approval folds into a standing profile; the profile fills the gaps in the next
spec and feeds the interview. Driven offline: the profile math is deterministic, and a real
build round-trips through it — approve once, and the next gap-spec inherits your taste.
"""

from __future__ import annotations

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.web_studio.aesthetics import AestheticCriteria
from orgs.web_studio.create import Review, build_create_page
from orgs.web_studio.interview import CreateSpec, spec_completeness
from orgs.web_studio.profile import (
    AestheticProfile,
    ProfileStore,
    apply_profile,
    profile_hint,
)

GOOD = ("<!doctype html><html><head><style>"
        "body{background:#0a0a0a;color:#ffffff;font-family:monospace;}"
        "a,button{color:#ffffff;background:#0a0a0a;font-family:monospace;}"
        "</style></head><body><nav><a href='#'>Home</a></nav><h1>Hi</h1><button>Go</button></body></html>")
DARK = AestheticCriteria(theme="dark", min_contrast=4.5, fonts=["monospace"], palette=["#0a0a0a", "#ffffff"])
SPEC_FULL = CreateSpec("Landing", "x", ["nav", "h1", "button"], DARK)
SPEC_GAP = CreateSpec("Landing 2", "x", ["nav", "h1", "button"], AestheticCriteria())  # no aesthetics


def test_update_accumulates_taste():
    p = AestheticProfile()
    p.update(AestheticCriteria(theme="dark", palette=["#0a0a0a", "#ffffff"], fonts=["Monospace"], min_contrast=4.5))
    assert p.approvals == 1 and p.theme() == "dark"
    assert {"rgb(10,10,10)", "rgb(255,255,255)"} <= set(p.palette)
    assert "monospace" in p.fonts and p.min_contrast == 4.5
    p.update(AestheticCriteria(theme="dark", fonts=["serif"], min_contrast=7.0))
    assert p.approvals == 2 and p.theme() == "dark" and "serif" in p.fonts
    assert p.min_contrast == 7.0  # strictest wins


def test_apply_profile_fills_gaps_without_overriding():
    p = AestheticProfile(approvals=1, theme_votes={"dark": 1}, palette=["rgb(10,10,10)"],
                         fonts=["monospace"], min_contrast=4.5)
    filled = apply_profile(p, SPEC_GAP)
    assert filled.aesthetics.theme == "dark" and filled.aesthetics.fonts == ["monospace"]
    assert spec_completeness(filled)[0]  # gaps filled -> now gateable
    explicit = apply_profile(p, CreateSpec("T", "d", ["h1"], AestheticCriteria(theme="light")))
    assert explicit.aesthetics.theme == "light"  # an explicit choice is never overridden


def test_profile_hint():
    assert profile_hint(AestheticProfile()) is None
    p = AestheticProfile(approvals=1, theme_votes={"dark": 1}, fonts=["monospace"])
    h = profile_hint(p)
    assert h and "dark" in h and "monospace" in h


def test_profile_store_round_trip(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    assert store.load().approvals == 0
    p = AestheticProfile()
    p.update(DARK)
    store.save(p)
    loaded = store.load()
    assert loaded.approvals == 1 and loaded.theme() == "dark" and "monospace" in loaded.fonts


def test_build_learns_then_a_gap_spec_inherits_the_taste(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    # build 1: explicit dark spec, approved -> the profile learns
    r1 = build_create_page(SPEC_FULL, ScriptedProvider({"web-developer": GOOD}),
                           MemoryStore(tmp_path / "m1"), review=lambda h, rr: Review(True),
                           profile_store=store)
    assert r1.accepted
    prof = store.load()
    assert prof.approvals == 1 and prof.theme() == "dark" and "monospace" in prof.fonts

    # build 2: a spec with NO aesthetics — the profile fills them, so it still builds & ships
    r2 = build_create_page(SPEC_GAP, ScriptedProvider({"web-developer": GOOD}),
                           MemoryStore(tmp_path / "m2"), review=lambda h, rr: Review(True),
                           profile_store=store)
    assert r2.accepted  # inherited the learned taste
    assert store.load().approvals == 2
