"""The Production Studio's cast — the proposers. Each writes the next artifact in the chain; the
deterministic gates decide whether it holds. Concept declares the world; the Scriptwriter may only
use what was declared; the Storyboard Artist may only illustrate real beats. The constraints are
in the prompts AND enforced by the gates — the prompt asks, the gate proves."""

from __future__ import annotations

from engine.artifact import Artifact
from engine.model import ModelProvider
from orgs.production_studio.production import Concept, Script, script_beats
from orgs.software_studio.agents import _strip_code_fences

CONCEPT_SYSTEM = (
    "You are a concept developer for short narrated videos. Given a brief, produce a CONCEPT as "
    "ONLY JSON: {\"title\":..., \"logline\":..., \"audience\":..., \"tone\":..., "
    "\"target_seconds\": <number>, \"entities\": [named characters/elements the video may show]}. "
    "The entities list is a contract — list EVERY character, object, or setting the script and "
    "visuals are allowed to use; nothing outside it may appear later. Include any narrator and the "
    "protagonist (by the exact name they'll be called). Output ONLY the JSON."
)

SCRIPT_SYSTEM = (
    "You are a scriptwriter for a short narrated video. Given a concept, write a SCRIPT as ONLY "
    "JSON: {\"scenes\": [{\"heading\":..., \"beats\": [{\"narration\":..., \"entities\": [...]}]}]}. "
    "HARD RULES: (1) every entity you list on a beat MUST be copied EXACTLY (same spelling) from "
    "the concept's declared entities — never rename one, never introduce a new character or object. "
    "If the story seems to need someone not on the list, you may not add them; work only with the "
    "declared entities. (2) Keep total narration near the target duration (about 2.5 words per "
    "second). Output ONLY the JSON."
)

STORYBOARD_SYSTEM = (
    "You are a storyboard artist. Given a script whose beats have stable ids, produce a STORYBOARD "
    "as ONLY JSON: {\"shots\": [{\"beat_id\":..., \"description\":..., \"entities\": [...]}]}. "
    "HARD RULES: (1) every beat id MUST have at least one shot — cover the whole script. (2) every "
    "shot's beat_id MUST be one of the given ids. (3) a shot may only show entities that the beat "
    "it illustrates lists. Output ONLY the JSON."
)


def _concept_brief(c: Concept) -> str:
    return (f"Title: {c.title}\nLogline: {c.logline}\nAudience: {c.audience}\nTone: {c.tone}\n"
            f"Target seconds: {c.target_seconds:g}\nDeclared entities (use ONLY these): "
            f"{', '.join(c.entities)}")


def _script_brief(script: Script) -> str:
    lines = []
    for b in script_beats(script):
        ents = ", ".join(b.entities) if b.entities else "(none)"
        lines.append(f"{b.id} [entities: {ents}]: {b.narration}")
    return "\n".join(lines)


def _with_feedback(prompt: str, feedback: str | None) -> str:
    if feedback:
        return f"Your previous attempt was REJECTED: {feedback}\nFix exactly that.\n\n{prompt}"
    return prompt


class ConceptAgent:
    role = "concept"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, brief: str, lessons: str = "", feedback: str | None = None) -> Artifact:
        prompt = _with_feedback(f"{lessons}Brief: {brief}" if lessons else f"Brief: {brief}", feedback)
        raw = self.provider.propose(role=self.role, prompt=prompt, system=CONCEPT_SYSTEM)
        return Artifact.propose(type="concept", owner="concept-agent",
                                payload=_strip_code_fences(raw), rationale=f"concept for: {brief}")


class ScriptwriterAgent:
    role = "scriptwriter"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, concept: Concept, lessons: str = "", feedback: str | None = None) -> Artifact:
        body = f"{lessons}{_concept_brief(concept)}" if lessons else _concept_brief(concept)
        raw = self.provider.propose(role=self.role, prompt=_with_feedback(body, feedback),
                                    system=SCRIPT_SYSTEM)
        return Artifact.propose(type="script", owner="scriptwriter-agent",
                                payload=_strip_code_fences(raw), rationale=f"script for: {concept.title}")


class StoryboardArtistAgent:
    role = "storyboard-artist"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, concept: Concept, script: Script, feedback: str | None = None) -> Artifact:
        body = (f"Concept tone: {concept.tone}\n\nScript beats (reference these ids):\n"
                f"{_script_brief(script)}")
        raw = self.provider.propose(role=self.role, prompt=_with_feedback(body, feedback),
                                    system=STORYBOARD_SYSTEM)
        return Artifact.propose(type="storyboard", owner="storyboard-artist-agent",
                                payload=_strip_code_fences(raw), rationale=f"storyboard for: {concept.title}")
