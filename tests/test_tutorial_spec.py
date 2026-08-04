"""hub/tutorial_spec.py — offline, deterministic.

Same convergence discipline as test_web_interview.py: the deterministic completeness check,
not the model, decides when the scope interview is actually done.
"""

from __future__ import annotations

import json

from engine.model import SequencedProvider
from hub.tutorial_spec import TutorialSpec, interview_for_scope, parse_tutorial_spec, spec_completeness

Q1 = '{"question": "How much depth do you want?"}'
COMPLETE = json.dumps({"spec": {
    "depth": "walkthrough", "reading_style": "detailed", "include_typing_practice": True,
}})
INCOMPLETE = json.dumps({"spec": {"depth": "walkthrough"}})  # no reading_style -> not complete


def test_completeness_passes_a_valid_spec():
    spec = parse_tutorial_spec(json.dumps(json.loads(COMPLETE)["spec"]))
    ok, missing = spec_completeness(spec)
    assert ok and missing == []


def test_completeness_flags_missing_reading_style():
    spec = parse_tutorial_spec(json.dumps(json.loads(INCOMPLETE)["spec"]))
    ok, missing = spec_completeness(spec)
    assert not ok and any("reading_style" in m for m in missing)


def test_completeness_rejects_an_invalid_depth_value():
    spec = TutorialSpec(depth="a_little_bit", reading_style="detailed", include_typing_practice=False)
    ok, missing = spec_completeness(spec)
    assert not ok and any("depth" in m for m in missing)


def test_interview_reaches_a_usable_spec():
    provider = SequencedProvider({"interviewer": [Q1, COMPLETE]})
    res = interview_for_scope("How Widgets Work", provider, answer=lambda q: "walkthrough, detailed, yes")
    assert res.spec is not None
    assert res.spec.depth == "walkthrough"
    assert res.spec.include_typing_practice is True


def test_interview_wont_stop_on_an_incomplete_spec():
    provider = SequencedProvider({"interviewer": [INCOMPLETE, Q1, COMPLETE]})
    res = interview_for_scope("How Widgets Work", provider, answer=lambda q: "detailed")
    assert res.spec is not None and spec_completeness(res.spec)[0]
    assert res.rounds == 3  # did not accept the round-1 incomplete spec
