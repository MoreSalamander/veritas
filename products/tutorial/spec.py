"""The scope interview for turning one shared video/webpage into a single-use tutorial.

Same discipline as orgs/web_studio/interview.py's P20 spec, now on engine.interview's shared
loop: the model proposes the next question or a finished spec, but a deterministic completeness
check decides when the interview can actually stop. Here the "goal" being interviewed toward
isn't a web page's design — it's how the person wants a Knowledge Graph source presented back to
them: how much depth, how much narration versus bare steps, and whether to practice any code the
source contains.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from engine.interview import InterviewResult, SpecParseError, extract_json, run_interview
from engine.model import ModelProvider


class TutorialSpecParseError(SpecParseError):
    """The proposed tutorial-scope spec is not usable JSON."""


@dataclass
class TutorialSpec:
    depth: str  # "overview" | "walkthrough" | "deep_dive"
    reading_style: str  # "essentials_only" | "detailed"
    include_typing_practice: bool


_VALID_DEPTHS = {"overview", "walkthrough", "deep_dive"}
_VALID_STYLES = {"essentials_only", "detailed"}


def parse_tutorial_spec(payload: str) -> TutorialSpec:
    try:
        obj = extract_json(payload)
    except SpecParseError as exc:
        raise TutorialSpecParseError(str(exc)) from exc
    return TutorialSpec(
        depth=str(obj.get("depth", "")).strip().lower(),
        reading_style=str(obj.get("reading_style", "")).strip().lower(),
        include_typing_practice=bool(obj.get("include_typing_practice", False)),
    )


def spec_completeness(spec: TutorialSpec) -> tuple[bool, list[str]]:
    """The deterministic score: is this spec usable to actually shape a tutorial? A depth and a
    reading style are required (they change what the generator produces); typing-practice
    inclusion always has a value (defaults False) so it never blocks completeness on its own."""
    missing: list[str] = []
    if spec.depth not in _VALID_DEPTHS:
        missing.append(f"depth (one of {sorted(_VALID_DEPTHS)})")
    if spec.reading_style not in _VALID_STYLES:
        missing.append(f"reading_style (one of {sorted(_VALID_STYLES)})")
    return (not missing, missing)


INTERVIEWER_SYSTEM = (
    "You are interviewing a person about how they want a shared video or webpage turned into a "
    "one-time tutorial they read instead of rewatching the source. You need ONLY: depth "
    '("overview"=key points only, "walkthrough"=step by step, "deep_dive"=comprehensive with '
    'context) and reading_style ("essentials_only"=just the necessary steps, "detailed"=full '
    "narration including sensory/contextual detail, e.g. \"the pan is hot, the sizzle is "
    "normal\" for a recipe). Optionally ask whether they want any code in the source turned into "
    "typing practice (include_typing_practice, true/false) if the topic sounds technical — skip "
    "this question entirely for non-technical topics. Ask ONE focused question at a time for "
    "whatever you don't yet know. Respond with ONLY JSON, no prose: either "
    '{"question": "..."} or {"spec": {"depth": ..., "reading_style": ..., '
    '"include_typing_practice": true|false}}.'
)

_FORCE_SPEC = (
    "You now have enough. Output the final spec JSON now — no more questions. Infer a reasonable "
    "include_typing_practice value (false if the topic isn't technical or wasn't mentioned). "
    "Required fields: depth, reading_style, include_typing_practice."
)


def interview_for_scope(
    goal: str, provider: ModelProvider, answer: Callable[[str], str],
    known: str | None = None, max_rounds: int = 6, force_after: int = 2,
) -> InterviewResult[TutorialSpec]:
    """Run the scope interview to a usable TutorialSpec. `goal` is normally the source's own
    title (e.g. a MemoryRecord.title from the Knowledge Graph)."""
    return run_interview(
        goal, provider, answer,
        system_prompt=INTERVIEWER_SYSTEM,
        parse_spec=parse_tutorial_spec,
        spec_completeness=spec_completeness,
        force_spec_message=_FORCE_SPEC,
        known=known, max_rounds=max_rounds, force_after=force_after,
    )
