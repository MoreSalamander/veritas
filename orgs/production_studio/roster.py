"""The Production Studio's roster, for the Hub's Org view. Cast authored here; gate HARD/SOFT read
straight off the gate classes so the page can't drift from the code."""

from __future__ import annotations

from typing import Any

from engine.gate import Gate
from engine.validation import ValidationGate
from orgs.production_studio.assets import (
    AssetConsistencyGate,
    AssetCoverageGate,
    AssetIntegrityGate,
)
from orgs.production_studio.editing import SequenceCoverageGate, TimelineIntegrityGate
from orgs.production_studio.gates import (
    ConceptScorerGate,
    DurationGate,
    ScriptGroundingGate,
    ScriptStructureGate,
    StoryboardCoverageGate,
    StoryboardGroundingGate,
)

_CAST: list[tuple[str, str, str]] = [
    ("Concept Developer", "concept", "Turns a brief into a concept: title, audience, tone, target length, and the declared entities the production may use — the contract everything downstream is held to."),
    ("Scriptwriter", "scriptwriter", "Writes the script in scenes and beats, using only the concept's declared entities; re-writes on rejection (e.g. \"undeclared entity: Narrator (s2b1)\")."),
    ("Storyboard Artist", "storyboard-artist", "Turns each script beat into shots, covering every beat and showing only the entities present in it; re-draws on rejection (e.g. \"uncovered beat: s1b3\")."),
    ("Asset Generator", "asset-generator", "Renders an image per shot and narration audio per beat, drawing each entity with its pinned reference (a tool call, not a model proposal — the gates are still the authority)."),
    ("Editor", "editor", "Lays the shots out in storyboard order and gives each its beat's narration time, producing a contiguous, in-sync timeline (a deterministic assembly the gates then verify)."),
]

_GATES: list[tuple[type[Gate], str, str]] = [
    (ConceptScorerGate, "concept", "the concept parses and is complete — otherwise there's no spec to verify against"),
    (ScriptStructureGate, "script", "the script parses into scenes and beats, all narrated"),
    (ScriptGroundingGate, "script", "every entity the script uses was declared in the concept — no character appears unauthorized"),
    (DurationGate, "script", "the narration's runtime is near the target length — advisory only"),
    (StoryboardCoverageGate, "storyboard", "every script beat has at least one shot — nothing is dropped"),
    (StoryboardGroundingGate, "storyboard", "every shot anchors a real beat and shows only that beat's entities — no orphans, nothing invented"),
    (AssetCoverageGate, "assets", "every shot has an image and every beat has narration audio — nothing missing"),
    (AssetIntegrityGate, "assets", "every asset file is a real, decodable image/audio of the size/duration it claims"),
    (AssetConsistencyGate, "assets", "each entity is drawn with one pinned reference across every shot — a character can't look different scene to scene"),
    (SequenceCoverageGate, "timeline", "the cut contains every shot, exactly once, in storyboard order — nothing dropped or reordered"),
    (TimelineIntegrityGate, "timeline", "the cut is contiguous from zero (no gaps/overlaps) and each beat's screen time matches its narration audio — audio/visual in sync"),
    (ValidationGate, "timeline", "final authority: every hard gate passed, provenance complete"),
]


def roster() -> dict[str, Any]:
    return {
        "cast": [{"name": n, "role": r, "produces": p} for n, r, p in _CAST],
        "gates": [
            {"name": g.name, "determinism": g.determinism.value, "scope": scope, "about": about}
            for g, scope, about in _GATES
        ],
        "principle": "A production is verified by CONSISTENCY THROUGH THE CHAIN, not by being "
        "good. The concept declares the world; the script may use only what was declared; the "
        "storyboard may cover only real beats and invent nothing. Referential integrity is a "
        "fact a machine can prove. Whether the result is compelling is judgment — the human tier.",
    }
