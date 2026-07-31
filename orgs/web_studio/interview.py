"""P20 — the interview that turns a vague goal into a gateable spec.

"Make me a stunning site" can't be verified — there's nothing to check. The interview fixes
that at the source: it asks questions until it has extracted criteria specific enough that the
gates (structure + the P19 aesthetic gates) can actually check them. The answers become the
spec; the checkable parts of that spec become the hard gates. Verification moves to the FRONT.

The Veritas discipline, applied to the interview itself: the model proposes the next question
(or a finished spec), but a *deterministic* completeness check — not the model — decides when
it's done. The interview can't stop until the spec is genuinely gateable. (This is the
scene/beats "interview until it can pass a score" pattern; here the score is `is it gateable`.)

The loop itself now lives in engine/interview.py — extracted so other domains (a shared
tutorial's scope, a recipe's presentation style) get the same convergence guarantee without a
second copy of it. This module is the CreateSpec-specific instance: its own spec type, its own
completeness check, its own interviewer system prompt, wired to the shared loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.interview import InterviewResult, SpecParseError, extract_json, run_interview
from engine.model import ModelProvider
from orgs.web_studio.aesthetics import AestheticCriteria


class CreateSpecParseError(SpecParseError):
    """The proposed create-spec is not usable JSON. The scorer rejects on this. Subclasses the
    shared SpecParseError so engine.interview's loop still catches it as one."""


@dataclass
class CreateSpec:
    title: str
    description: str
    required_elements: list[str]  # CSS selectors the page must contain (structure gate)
    aesthetics: AestheticCriteria  # the measurable design intent (P19 gates)


def _extract_json(text: str) -> dict[str, object]:
    try:
        return extract_json(text)
    except SpecParseError as exc:
        raise CreateSpecParseError(str(exc)) from exc


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


def interview(
    goal: str, provider: ModelProvider, answer: Callable[[str], str], known: str | None = None,
    max_rounds: int = 8, force_after: int = 2,
) -> InterviewResult[CreateSpec]:
    """Run the interview to a gateable CreateSpec. `answer` supplies the human's reply to a
    question (a real person in the hub; a scripted fn in tests). `known` is a summary of the
    user's learned preferences (from the aesthetic profile) so the interview doesn't re-ask them
    — it shortens over time. Thin wrapper over engine.interview's shared loop; see that module
    for the actual convergence discipline."""
    return run_interview(
        goal, provider, answer,
        system_prompt=INTERVIEWER_SYSTEM,
        parse_spec=parse_create_spec,
        spec_completeness=spec_completeness,
        force_spec_message=_FORCE_SPEC,
        known=known, max_rounds=max_rounds, force_after=force_after,
    )
