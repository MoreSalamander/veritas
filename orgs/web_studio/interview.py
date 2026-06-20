"""P20 — the interview that turns a vague goal into a gateable spec.

"Make me a stunning site" can't be verified — there's nothing to check. The interview fixes
that at the source: it asks questions until it has extracted criteria specific enough that the
gates (structure + the P19 aesthetic gates) can actually check them. The answers become the
spec; the checkable parts of that spec become the hard gates. Verification moves to the FRONT.

The Veritas discipline, applied to the interview itself: the model proposes the next question
(or a finished spec), but a *deterministic* completeness check — not the model — decides when
it's done. The interview can't stop until the spec is genuinely gateable. (This is the
scene/beats "interview until it can pass a score" pattern; here the score is `is it gateable`.)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.model import ModelProvider
from orgs.web_studio.aesthetics import AestheticCriteria


class CreateSpecParseError(ValueError):
    """The proposed create-spec is not usable JSON. The scorer rejects on this."""


@dataclass
class CreateSpec:
    title: str
    description: str
    required_elements: list[str]  # CSS selectors the page must contain (structure gate)
    aesthetics: AestheticCriteria  # the measurable design intent (P19 gates)


def _extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise CreateSpecParseError("no JSON object found")
    try:
        obj: Any = json.loads(text[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise CreateSpecParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise CreateSpecParseError("not a JSON object")
    return obj


def parse_create_spec(payload: str) -> CreateSpec:
    obj = _extract_json(payload)
    raw_elems = obj.get("required_elements", [])
    elements = [str(s).strip() for s in raw_elems if isinstance(s, str) and s.strip()] \
        if isinstance(raw_elems, list) else []
    a = obj.get("aesthetics") or {}
    aesthetics = AestheticCriteria(
        theme=a.get("theme"),
        min_contrast=(float(a["min_contrast"]) if a.get("min_contrast") is not None else None),
        fonts=([str(f) for f in a["fonts"]] if isinstance(a.get("fonts"), list) else None),
        palette=([str(c) for c in a["palette"]] if isinstance(a.get("palette"), list) else None),
    ) if isinstance(a, dict) else AestheticCriteria()
    return CreateSpec(
        title=str(obj.get("title", "")).strip(),
        description=str(obj.get("description", "")).strip(),
        required_elements=elements,
        aesthetics=aesthetics,
    )


def spec_completeness(spec: CreateSpec) -> tuple[bool, list[str]]:
    """The deterministic 'score' the interview drives toward: is this spec GATEABLE?
    Gateable = it has a title, at least one required element (so the structure gate has
    something), and at least one measurable aesthetic criterion (so an aesthetic gate has
    something). Returns (complete, missing-fields)."""
    missing: list[str] = []
    if not spec.title:
        missing.append("title")
    if not spec.required_elements:
        missing.append("required_elements")
    a = spec.aesthetics
    if a.theme is None and a.min_contrast is None and not a.fonts and not a.palette:
        missing.append("aesthetics")
    return (not missing, missing)


class CreateSpecScorerGate(Gate):
    """HARD: the spec is gateable (parses + complete) — otherwise there's nothing to verify a
    build against. The create-mode analogue of the software org's spec-scorer."""

    name = "create-spec"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            spec = parse_create_spec(artifact.payload)
        except CreateSpecParseError as exc:
            return self._result(False, f"spec not usable: {exc}")
        complete, missing = spec_completeness(spec)
        if not complete:
            return self._result(False, f"spec not gateable yet — missing: {', '.join(missing)}")
        return self._result(
            True, f"gateable: {len(spec.required_elements)} required element(s) + measurable aesthetics"
        )


INTERVIEWER_SYSTEM = (
    "You are interviewing a user to design a web page. Your job is to gather enough to write a "
    "VERIFIABLE spec — so the result can be checked, not just admired. You need ONLY: a title, the "
    "page's required elements (as CSS selectors it must contain, e.g. \"header\",\"nav\",\"h1\","
    "\"#cta\",\"footer\"), and the measurable aesthetic: theme (\"dark\"|\"light\"), a small color "
    "palette (hex), allowed fonts, and a minimum text contrast. Ask ONE focused question at a time "
    "for whatever you don't yet know — and ONLY about those fields, nothing else (copy, imagery, "
    "and feature details are NOT needed). As soon as you can fill those fields, output the spec; "
    "do not keep asking once you have enough. Respond with ONLY JSON, no prose: either {\"question"
    "\": \"...\"} or {\"spec\": {\"title\":..., \"description\":..., \"required_elements\":[...], "
    "\"aesthetics\": {\"theme\":..., \"min_contrast\":..., \"fonts\":[...], \"palette\":[...]}}}."
)

# The deterministic terminator. The whole discipline is that a pure check — not the model — decides
# when the interview is done; but the check only runs on a spec, and a chatty model can ask forever
# and never volunteer one. So once the user has answered enough rounds, we stop letting it ask and
# force it to synthesize the spec from what it has. The completeness check still rules on the result,
# so a forced-but-incomplete spec doesn't slip through — it just redirects the next question.
_FORCE_SPEC = (
    "You now have enough. Output the final spec JSON now — no more questions. Use everything the "
    "user has told you and infer reasonable values for any minor detail. Required fields: title, "
    "required_elements (CSS selectors), and aesthetics (theme, palette, fonts, min_contrast)."
)


@dataclass
class InterviewResult:
    spec: CreateSpec | None  # None if a gateable spec wasn't reached within the round budget
    transcript: list[tuple[str, str]] = field(default_factory=list)  # (question, answer) pairs
    rounds: int = 0


class InterviewerAgent:
    role = "interviewer"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def next(self, goal: str, transcript: list[tuple[str, str]], nudge: str | None = None,
             known: str | None = None) -> dict[str, Any]:
        lines = [f"Goal: {goal}"]
        if known:
            lines += [f"Known user preferences (do NOT re-ask these): {known}"]
        lines += [""]
        for q, a in transcript:
            lines += [f"Q: {q}", f"A: {a}"]
        if nudge:
            lines += ["", nudge]
        raw = self.provider.propose(role=self.role, prompt="\n".join(lines), system=INTERVIEWER_SYSTEM)
        return _extract_json(raw)


def interview(
    goal: str, provider: ModelProvider, answer: Callable[[str], str],
    known: str | None = None, max_rounds: int = 8, force_after: int = 2,
) -> InterviewResult:
    """Run the interview to a gateable spec. `answer` supplies the human's reply to a question
    (a real person in the hub; a scripted fn in tests). `known` is a summary of the user's learned
    preferences (from the aesthetic profile) so the interview doesn't re-ask them — it shortens
    over time. The loop ends when `spec_completeness` says the spec is gateable, or the budget runs
    out. After `force_after` answered questions the model is forced to synthesize a spec instead of
    being allowed to keep asking (so a chatty model converges); the completeness check still decides
    whether that forced spec is acceptable."""
    transcript: list[tuple[str, str]] = []
    agent = InterviewerAgent(provider)
    nudge: str | None = None
    questions_asked = 0
    for rnd in range(1, max_rounds + 1):
        # past the budget, stop letting it ask — make it finalize (unless a more specific nudge,
        # e.g. a missing-field redirect, is already pending).
        if questions_asked >= force_after and nudge is None:
            nudge = _FORCE_SPEC
        try:
            parsed = agent.next(goal, transcript, nudge, known)
        except CreateSpecParseError:
            nudge = "Your last reply was not valid JSON. Respond with ONLY the JSON object."
            continue
        if "question" in parsed and isinstance(parsed["question"], str):
            q = parsed["question"]
            transcript.append((q, answer(q)))
            questions_asked += 1
            # once we've hit the budget, the next turn forces a spec instead of another question
            nudge = _FORCE_SPEC if questions_asked >= force_after else None
            continue
        if "spec" in parsed:
            try:
                spec = parse_create_spec(json.dumps(parsed["spec"]))
            except CreateSpecParseError:
                nudge = "That spec was malformed. Output a valid spec JSON now."
                continue
            complete, missing = spec_completeness(spec)
            if complete:
                return InterviewResult(spec=spec, transcript=transcript, rounds=rnd)
            # the model thinks it's done; the deterministic check disagrees — redirect to the gap
            nudge = (f"The spec is missing: {', '.join(missing)}. Output a corrected spec JSON now, "
                     "asking the user only if a value is genuinely unknowable.")
            continue
        nudge = "Reply with either {\"question\": ...} or {\"spec\": ...}."
    return InterviewResult(spec=None, transcript=transcript, rounds=max_rounds)
