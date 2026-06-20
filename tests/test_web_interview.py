"""P20 — the interview that manufactures the gate.

A vague goal becomes a gateable spec, and crucially: the loop's stop condition is the
deterministic `spec_completeness`, not the model's say-so. Even if the model declares a spec
'done', an incomplete one keeps the interview going. The model proposes questions; the pure
check decides when verification is possible.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from engine.model import SequencedProvider
from orgs.web_studio.interview import (
    CreateSpecScorerGate,
    interview,
    parse_create_spec,
    spec_completeness,
)

Q1 = '{"question": "What is the page for?"}'
Q2 = '{"question": "Dark or light, which colors, which fonts?"}'
COMPLETE = json.dumps({"spec": {
    "title": "Landing", "description": "a landing page",
    "required_elements": ["nav", "h1", "button"],
    "aesthetics": {"theme": "dark", "min_contrast": 4.5, "fonts": ["monospace"],
                   "palette": ["#0a0a0a", "#ffffff"]}}})
INCOMPLETE = json.dumps({"spec": {  # no aesthetics -> not gateable
    "title": "Landing", "description": "x", "required_elements": ["nav", "h1"]}})


# --- the deterministic 'score' ----------------------------------------------------

def test_completeness_passes_a_gateable_spec():
    spec = parse_create_spec(json.dumps(json.loads(COMPLETE)["spec"]))
    ok, missing = spec_completeness(spec)
    assert ok and missing == []


def test_completeness_flags_missing_aesthetics():
    spec = parse_create_spec(json.dumps(json.loads(INCOMPLETE)["spec"]))
    ok, missing = spec_completeness(spec)
    assert not ok and "aesthetics" in missing


def test_scorer_gate_rejects_prose_and_incomplete():
    prose = Artifact.propose(type="create-spec", owner="t", payload="make it pretty", rationale="t")
    assert not CreateSpecScorerGate().check(prose).passed
    inc = Artifact.propose(type="create-spec", owner="t", payload=json.dumps(json.loads(INCOMPLETE)["spec"]), rationale="t")
    res = CreateSpecScorerGate().check(inc)
    assert not res.passed and "aesthetics" in res.evidence


# --- the interview loop -----------------------------------------------------------

def test_interview_reaches_a_gateable_spec():
    provider = SequencedProvider({"interviewer": [Q1, Q2, COMPLETE]})
    res = interview("a landing page", provider, answer=lambda q: "dark, navy & white, sans-serif")
    assert res.spec is not None and res.rounds == 3
    assert spec_completeness(res.spec)[0]
    assert res.spec.required_elements == ["nav", "h1", "button"]
    assert res.spec.aesthetics.theme == "dark"
    assert len(res.transcript) == 2  # two questions were answered


def test_interview_wont_stop_on_an_incomplete_spec():
    # model declares 'done' with no aesthetics; the deterministic check forces it to continue
    provider = SequencedProvider({"interviewer": [INCOMPLETE, Q1, COMPLETE]})
    res = interview("a landing page", provider, answer=lambda q: "dark, navy & white")
    assert res.spec is not None and res.rounds == 3  # did NOT accept the round-1 incomplete spec
    assert spec_completeness(res.spec)[0]


def test_interview_gives_up_if_never_gateable():
    provider = SequencedProvider({"interviewer": [Q1, Q2, Q1, Q2]})
    res = interview("x", provider, answer=lambda q: "dunno", max_rounds=4)
    assert res.spec is None  # never reached a gateable spec within the budget


class _ChattyProvider:
    """Models the real failure mode: a model that over-clarifies and never volunteers a spec on
    its own — it keeps asking UNLESS explicitly forced to finalize, then it emits the spec."""

    def propose(self, *, role: str, prompt: str, system: str | None = None) -> str:
        forced = "no more questions" in prompt.lower() or "output the final spec" in prompt.lower()
        return COMPLETE if forced else Q1


def test_interview_forces_convergence_on_a_chatty_model():
    # without forcing this model would ask Q1 forever and hit the budget (spec=None); the
    # deterministic budget makes it finalize, and completeness accepts the forced spec.
    res = interview("a landing page", _ChattyProvider(), answer=lambda q: "ok", force_after=2)
    assert res.spec is not None and spec_completeness(res.spec)[0]
    assert res.rounds <= 4  # converged quickly, did not exhaust the round budget
