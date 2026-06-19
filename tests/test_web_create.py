"""P21 — create mode: build to spec, manufactured hard gates, then the human is the gate.

The measurable bar (structure + P19 aesthetics) is enforced automatically; the human only
judges the residue. Approve → ships human-approved (the third trust tier, recorded in the
ledger). Request changes → re-propose. A page that can't even meet the measurable bar never
reaches the human. Driven offline: real renders, scripted developer + scripted reviewer.
"""

from __future__ import annotations

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.web_studio.aesthetics import AestheticCriteria
from orgs.web_studio.create import Review, build_create_page
from orgs.web_studio.interview import CreateSpec

SPEC = CreateSpec(
    title="Landing", description="a landing page", required_elements=["nav", "h1", "button"],
    aesthetics=AestheticCriteria(theme="dark", min_contrast=4.5, fonts=["monospace"],
                                 palette=["#0a0a0a", "#ffffff"]),
)
GOOD = ("<!doctype html><html><head><style>"
        "body{background:#0a0a0a;color:#ffffff;font-family:monospace;}"
        "a,button{color:#ffffff;background:#0a0a0a;font-family:monospace;}"
        "</style></head><body><nav><a href='#'>Home</a></nav><h1>Hi</h1><button>Go</button></body></html>")
NO_BUTTON = GOOD.replace("<button>Go</button>", "")  # violates structure (required button)


def test_approve_first_try_ships_human_approved(tmp_path):
    res = build_create_page(SPEC, ScriptedProvider({"web-developer": GOOD}),
                            MemoryStore(tmp_path), review=lambda html, r: Review(True))
    assert res.accepted and res.machine_verified and res.iterations == 1
    assert res.page_outcome is not None and res.page_outcome.accepted
    gates = {g.gate_name: g for g in res.page_outcome.artifact.provenance.gate_results}
    # the manufactured hard gates + the human tier are all in the ledger
    assert {"render", "structure", "theme", "contrast", "fonts", "palette", "human-approval"} <= set(gates)
    human = gates["human-approval"]
    assert human.passed and human.determinism.value == "human"
    assert res.page_outcome.memory_path.parent.name == "institutional"


def test_feedback_then_approve(tmp_path):
    calls = []

    def review(html, r):
        calls.append(1)
        return Review(True) if len(calls) >= 2 else Review(False, "more whitespace, please")

    res = build_create_page(SPEC, ScriptedProvider({"web-developer": GOOD}),
                            MemoryStore(tmp_path), review=review)
    assert res.accepted and res.iterations == 2


def test_measurable_miss_never_reaches_the_human(tmp_path):
    asked = []

    def review(html, r):
        asked.append(1)
        return Review(True)

    res = build_create_page(SPEC, ScriptedProvider({"web-developer": NO_BUTTON}),
                            MemoryStore(tmp_path), review=review)
    assert not res.accepted and not res.machine_verified
    assert not asked  # the hard floor blocked it before any human judgment


def test_machine_verified_but_never_approved(tmp_path):
    res = build_create_page(SPEC, ScriptedProvider({"web-developer": GOOD}),
                            MemoryStore(tmp_path), review=lambda html, r: Review(False, "nope"))
    assert not res.accepted and res.machine_verified
    assert res.page_outcome is None  # met the measurable bar, but the human never signed off
