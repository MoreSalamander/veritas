"""P20, generalized — the interview that manufactures a gateable spec, for any domain.

The discipline, unchanged from where it was first proven (orgs/web_studio/interview.py, a
web page's CreateSpec): the model proposes the next question, or a finished spec, but a
DETERMINISTIC completeness check — never the model's own say-so — decides when the interview
is actually done. A model that declares itself finished with an incomplete spec gets redirected,
not believed. A chatty model that never volunteers a spec gets forced to finalize after a round
budget, and the completeness check still rules on what it produces.

Extracted here so a new domain (a shared-video/webpage tutorial's scope, a recipe's read-along
style, eventually a weekly meal plan) gets the identical convergence guarantee without copying
the loop a second time — the same DRY-over-copy-paste choice this repo has made before for its
four presets and, again, for the three Hunter engines sharing one bridge.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from engine.model import ModelProvider

SpecT = TypeVar("SpecT")


class SpecParseError(ValueError):
    """A domain's spec payload wasn't usable JSON. Domain modules may subclass this to keep
    their own exception identity (see orgs/web_studio/interview.py's CreateSpecParseError) —
    subclassing, not replacing, so the shared loop's `except SpecParseError` still catches it."""


def extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise SpecParseError("no JSON object found")
    try:
        obj: Any = json.loads(text[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise SpecParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise SpecParseError("not a JSON object")
    return obj


@dataclass
class InterviewResult(Generic[SpecT]):
    spec: SpecT | None  # None if a gateable spec wasn't reached within the round budget
    transcript: list[tuple[str, str]] = field(default_factory=list)  # (question, answer) pairs
    rounds: int = 0


class InterviewerAgent:
    role = "interviewer"

    def __init__(self, provider: ModelProvider, system_prompt: str) -> None:
        self.provider = provider
        self._system = system_prompt

    def next(
        self, goal: str, transcript: list[tuple[str, str]], nudge: str | None = None,
        known: str | None = None,
    ) -> dict[str, Any]:
        lines = [f"Goal: {goal}"]
        if known:
            lines += [f"Known user preferences (do NOT re-ask these): {known}"]
        lines += [""]
        for q, a in transcript:
            lines += [f"Q: {q}", f"A: {a}"]
        if nudge:
            lines += ["", nudge]
        raw = self.provider.propose(role=self.role, prompt="\n".join(lines), system=self._system)
        return extract_json(raw)


def run_interview(
    goal: str,
    provider: ModelProvider,
    answer: Callable[[str], str],
    *,
    system_prompt: str,
    parse_spec: Callable[[str], SpecT],
    spec_completeness: Callable[[SpecT], tuple[bool, list[str]]],
    force_spec_message: str,
    known: str | None = None,
    max_rounds: int = 8,
    force_after: int = 2,
) -> InterviewResult[SpecT]:
    """Domain-agnostic interview loop. `parse_spec` turns a model-declared spec's JSON into the
    domain's own spec type; `spec_completeness` is the deterministic score that decides whether
    the interview can stop — see module docstring for the discipline this preserves. `answer`
    supplies the human's reply to a question (a real person in the hub; a scripted fn in tests).
    """
    transcript: list[tuple[str, str]] = []
    agent = InterviewerAgent(provider, system_prompt)
    nudge: str | None = None
    questions_asked = 0
    for rnd in range(1, max_rounds + 1):
        # past the budget, stop letting it ask — make it finalize (unless a more specific nudge,
        # e.g. a missing-field redirect, is already pending).
        if questions_asked >= force_after and nudge is None:
            nudge = force_spec_message
        try:
            parsed = agent.next(goal, transcript, nudge, known)
        except SpecParseError:
            nudge = "Your last reply was not valid JSON. Respond with ONLY the JSON object."
            continue
        if "question" in parsed and isinstance(parsed["question"], str):
            q = parsed["question"]
            transcript.append((q, answer(q)))
            questions_asked += 1
            nudge = force_spec_message if questions_asked >= force_after else None
            continue
        if "spec" in parsed:
            try:
                spec = parse_spec(json.dumps(parsed["spec"]))
            except SpecParseError:
                nudge = "That spec was malformed. Output a valid spec JSON now."
                continue
            complete, missing = spec_completeness(spec)
            if complete:
                return InterviewResult(spec=spec, transcript=transcript, rounds=rnd)
            # the model thinks it's done; the deterministic check disagrees — redirect to the gap
            nudge = (
                f"The spec is missing: {', '.join(missing)}. Output a corrected spec JSON now, "
                "asking the user only if a value is genuinely unknowable."
            )
            continue
        nudge = 'Reply with either {"question": ...} or {"spec": ...}.'
    return InterviewResult(spec=None, transcript=transcript, rounds=max_rounds)
