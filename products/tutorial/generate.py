"""Turns a real Knowledge Graph source + a scope TutorialSpec into a single-use tutorial —
the actual content generation step, gated the same way every other proposal in this codebase
is: the model proposes, a deterministic check decides whether it's usable.

The shape is a step-by-step manual (materials up front, ordered sections of imperative steps,
optional per-section tips, a closing quick-reference of key values) — the build-it pipeline's own
shape (chapters -> steps), generalized past code: a `code` field is per-step and optional rather
than assumed, and `materials` covers ingredients-with-amounts, tools/parts, or software
prerequisites depending on what the source actually is. The EARLIER version of this module reused
myAIstro's flat lesson shape (summary/key_concepts/definitions) — measured live to be wrong for
anything procedural: a recipe rendered as "key concepts" has no ingredients or amounts, because
that shape has no slot for them. This shape does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.interview import SpecParseError, extract_json
from engine.memory import MemoryRecord
from engine.model import ModelProvider
from products.tutorial.spec import TutorialSpec


class TutorialContentParseError(SpecParseError):
    """The proposed tutorial content is not usable JSON."""


@dataclass
class TutorialStep:
    instruction: str  # one imperative action — "press X to delete the default cube"
    code: str = ""  # verbatim code/expression for this step, empty when not applicable


@dataclass
class TutorialSection:
    title: str  # e.g. "Scene Setup", "Whip the egg whites", "Remove the old disposal"
    steps: list[TutorialStep] = field(default_factory=list)
    intro: str = ""  # optional context before the steps — empty when the steps stand alone
    tip: str = ""  # optional callout — a gotcha, a substitution, a common mistake


@dataclass
class TutorialContent:
    overview: str  # what you'll end up with and why, 1-3 sentences
    materials: list[str] = field(default_factory=list)  # ingredients+amounts / tools+parts / prerequisites
    sections: list[TutorialSection] = field(default_factory=list)
    reference: list[str] = field(default_factory=list)  # closing cheat-sheet of key values/settings


def _str_list(obj: dict[str, Any], key: str) -> list[str]:
    raw = obj.get(key, [])
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]


def _parse_steps(raw: Any) -> list[TutorialStep]:
    if not isinstance(raw, list):
        return []
    steps: list[TutorialStep] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        instruction = str(item.get("instruction", "")).strip()
        if not instruction:
            continue
        steps.append(TutorialStep(instruction=instruction, code=str(item.get("code", "")).strip()))
    return steps


def _parse_sections(raw: Any) -> list[TutorialSection]:
    if not isinstance(raw, list):
        return []
    sections: list[TutorialSection] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        steps = _parse_steps(item.get("steps"))
        if not title or not steps:
            continue
        sections.append(TutorialSection(
            title=title, steps=steps,
            intro=str(item.get("intro", "")).strip(),
            tip=str(item.get("tip", "")).strip(),
        ))
    return sections


def parse_tutorial_content(payload: str) -> TutorialContent:
    try:
        obj = extract_json(payload)
    except SpecParseError as exc:
        raise TutorialContentParseError(str(exc)) from exc
    return TutorialContent(
        overview=str(obj.get("overview", "")).strip(),
        materials=_str_list(obj, "materials"),
        sections=_parse_sections(obj.get("sections")),
        reference=_str_list(obj, "reference"),
    )


def content_completeness(content: TutorialContent, spec: TutorialSpec) -> tuple[bool, list[str]]:
    """The deterministic score: is this usable AND does it respect the scope the person actually
    asked for? No overview means nothing to orient by; no materials means the single most common
    real failure this shape exists to prevent — a recipe with no ingredients, a build with no
    parts list — slipped through silently. Code present on any step when the interview said
    include_typing_practice=False is the generator inventing content the person didn't ask for."""
    missing: list[str] = []
    if not content.overview:
        missing.append("overview")
    if not content.materials:
        missing.append("materials (ingredients/tools/prerequisites)")
    if not content.sections:
        missing.append("sections")
    if not spec.include_typing_practice and any(s.code for sec in content.sections for s in sec.steps):
        missing.append("step code must be empty — the interview said include_typing_practice=False")
    return (not missing, missing)


class TutorialContentScorerGate(Gate):
    """HARD: the content is usable (parses + has an overview, materials, and real steps) and
    honors the spec's scope — the tutorial-generation analogue of CreateSpecScorerGate/ReportScorerGate."""

    name = "tutorial-content"
    determinism = Determinism.HARD

    def __init__(self, spec: TutorialSpec) -> None:
        self._spec = spec

    def check(self, artifact: Artifact) -> GateResult:
        try:
            content = parse_tutorial_content(artifact.payload)
        except TutorialContentParseError as exc:
            return self._result(False, f"content not usable: {exc}")
        complete, missing = content_completeness(content, self._spec)
        if not complete:
            return self._result(False, f"content rejected — {', '.join(missing)}")
        step_count = sum(len(sec.steps) for sec in content.sections)
        return self._result(
            True,
            f"usable: {len(content.materials)} material(s), {len(content.sections)} section(s), "
            f"{step_count} step(s), scope respected",
        )


GENERATOR_SYSTEM = (
    "You are turning a video or webpage transcript into a step-by-step manual someone follows "
    "instead of rewatching the source — the same shape as a good recipe card or an assembly "
    "guide: what you need, then ordered steps grouped into named sections. Follow the requested "
    "scope exactly: depth 'overview'=the main sections only, one step each; 'walkthrough'=every "
    "real step in order; 'deep_dive'=every step plus the reasoning/gotchas behind non-obvious "
    "ones. reading_style 'essentials_only'=terse imperative steps only; 'detailed'=include "
    "sensory/situational cues where the source has them (e.g. \"the pan is hot, the sizzle is "
    "normal\", \"it will blink open and vanish — that's expected\").\n\n"
    "CRITICAL: extract every concrete number the source states — ingredient amounts, "
    "temperatures, times, measurements, tool/part names, software settings — verbatim into "
    "`materials` (what's needed before starting) or into the relevant step/`reference` entry. "
    "Never invent a quantity, value, or setting the source doesn't actually state. A tutorial "
    "missing the amounts is useless — that is the single most important thing this format exists "
    "to preserve.\n\n"
    "Respond with ONLY JSON, this exact shape:\n"
    '{"overview": "<1-3 sentences: what you will end up with>", '
    '"materials": ["<ingredient with amount, or tool/part, or software+version, verbatim from '
    'the source>", ...], '
    '"sections": [{"title": "<short section name>", "intro": "<optional 1-2 sentence context, '
    'or \\"\\">", "steps": [{"instruction": "<one imperative action>", "code": "<verbatim code '
    'or expression for this step, or \\"\\">"}], "tip": "<optional callout, or \\"\\">"}], '
    '"reference": ["<optional key value/setting worth remembering, e.g. \\"Oven: 375\\u00b0F for '
    '25 min\\">", ...]}. '
    "`code` on any step MUST be left empty unless typing practice was explicitly requested — "
    "never invent code that isn't verbatim from the source text."
)


class TutorialGeneratorAgent:
    role = "tutorial-generator"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, source: MemoryRecord, spec: TutorialSpec) -> Artifact:
        prompt = (
            f"Source title: {source.title}\n"
            f"Requested scope: depth={spec.depth}, reading_style={spec.reading_style}, "
            f"include_typing_practice={spec.include_typing_practice}\n\n"
            f"Source text:\n{source.body}"
        )
        raw = self.provider.propose(role=self.role, prompt=prompt, system=GENERATOR_SYSTEM)
        return Artifact.propose(
            type="tutorial",
            owner="tutorial-generator-agent",
            payload=raw,
            rationale=f"single-use tutorial from: {source.title!r}, scope={spec.depth}/{spec.reading_style}",
        )


def tutorial_record(source: MemoryRecord, spec: TutorialSpec, artifact: Artifact) -> MemoryRecord:
    """Veritas's own record of a dispensed tutorial — kept in Veritas's memory regardless of
    whether any downstream system (e.g. myAIstro) also gets a copy. `body` is the artifact's own
    gated JSON payload, so a reader can pass it straight back through `parse_tutorial_content`
    with no separate format to maintain. Only ever call this on an ACCEPTED artifact."""
    prov = {
        "created_by": artifact.provenance.created_by,
        "rationale": artifact.provenance.rationale,
        "accepted_because": artifact.provenance.accepted_because,
        "source_id": source.id,
        "source_title": source.title,
        "source_url": source.provenance.get("url"),
        "source_channel": source.provenance.get("channel"),
        "depth": spec.depth,
        "reading_style": spec.reading_style,
        "include_typing_practice": spec.include_typing_practice,
    }
    return MemoryRecord(
        category="artifact",
        title=source.title,
        body=artifact.payload,
        source_artifact_id=artifact.id,
        tags=["tutorial", spec.depth, spec.reading_style],
        provenance=prov,
    )


def generate_tutorial(
    source: MemoryRecord, spec: TutorialSpec, provider: ModelProvider,
) -> tuple[Artifact, GateResult]:
    """Propose tutorial content from a real Knowledge Graph source and gate it. Returns the
    artifact and its verdict — the caller decides what to do with a rejected one (retry, or
    surface the gate's evidence honestly rather than persisting anyway)."""
    agent = TutorialGeneratorAgent(provider)
    artifact = agent.propose(source, spec)
    gate = TutorialContentScorerGate(spec)
    result = gate.check(artifact)
    artifact.record_gate(result)
    if result.passed:
        artifact.accept(because=result.evidence)
    else:
        artifact.reject()
    return artifact, result
