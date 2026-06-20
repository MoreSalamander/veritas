"""The Production Studio's artifacts: Concept -> Script -> Storyboard.

These are typed so that "consistent" becomes checkable. The Concept declares the entities
(characters/elements) the production may use; the Script may reference only those; the Storyboard
may cover only real script beats and show only entities present in the beat it illustrates. Beat
ids are assigned deterministically on parse so the downstream Storyboard has stable anchors to
reference — the model never has to invent matching ids, it just has to point at real ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Narration pace for the duration estimate: ~150 words/minute = 2.5 words/second.
WORDS_PER_SECOND = 2.5


class ProductionParseError(ValueError):
    """A proposed artifact is not usable. The owning scorer/structure gate rejects on this."""


def _norm(s: str) -> str:
    """Case/space-insensitive form for entity matching — "Maya " and "maya" are one entity."""
    return " ".join(s.split()).lower()


def _extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ProductionParseError("no JSON object found")
    try:
        obj: Any = json.loads(text[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise ProductionParseError(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProductionParseError("not a JSON object")
    return obj


def _str_list(raw: Any) -> list[str]:
    return [str(x).strip() for x in raw if isinstance(x, str) and x.strip()] \
        if isinstance(raw, list) else []


# --- Concept (the root spec everything traces back to) -----------------------------------

@dataclass
class Concept:
    title: str
    logline: str
    audience: str
    tone: str
    target_seconds: float
    entities: list[str]  # the only characters/elements the script and visuals may use


def parse_concept(payload: str) -> Concept:
    obj = _extract_json(payload)
    try:
        target = float(obj.get("target_seconds", 0) or 0)
    except (ValueError, TypeError):
        target = 0.0
    return Concept(
        title=str(obj.get("title", "")).strip(),
        logline=str(obj.get("logline", "")).strip(),
        audience=str(obj.get("audience", "")).strip(),
        tone=str(obj.get("tone", "")).strip(),
        target_seconds=target,
        entities=_str_list(obj.get("entities")),
    )


def concept_completeness(c: Concept) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if not c.title:
        missing.append("title")
    if not c.logline:
        missing.append("logline")
    if not c.audience:
        missing.append("audience")
    if not c.tone:
        missing.append("tone")
    if c.target_seconds <= 0:
        missing.append("target_seconds")
    if not c.entities:
        missing.append("entities")
    return (not missing, missing)


# --- Script (scenes -> beats; beats reference declared entities) -------------------------

@dataclass
class Beat:
    id: str  # assigned on parse: s{scene}b{beat}
    narration: str
    entities: list[str]


@dataclass
class Scene:
    heading: str
    beats: list[Beat]


@dataclass
class Script:
    scenes: list[Scene]


def parse_script(payload: str) -> Script:
    obj = _extract_json(payload)
    raw_scenes = obj.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ProductionParseError("script has no scenes")
    scenes: list[Scene] = []
    for si, rs in enumerate(raw_scenes, start=1):
        if not isinstance(rs, dict):
            raise ProductionParseError(f"scene {si} is not an object")
        raw_beats = rs.get("beats")
        if not isinstance(raw_beats, list) or not raw_beats:
            raise ProductionParseError(f"scene {si} has no beats")
        beats: list[Beat] = []
        for bi, rb in enumerate(raw_beats, start=1):
            if not isinstance(rb, dict):
                raise ProductionParseError(f"scene {si} beat {bi} is not an object")
            narration = str(rb.get("narration", "")).strip()
            beats.append(Beat(id=f"s{si}b{bi}", narration=narration,
                              entities=_str_list(rb.get("entities"))))
        scenes.append(Scene(heading=str(rs.get("heading", "")).strip(), beats=beats))
    return Script(scenes=scenes)


def script_beats(script: Script) -> list[Beat]:
    return [b for scene in script.scenes for b in scene.beats]


def estimated_seconds(script: Script) -> float:
    words = sum(len(b.narration.split()) for b in script_beats(script))
    return words / WORDS_PER_SECOND


# --- Storyboard (shots cover script beats; show only beat entities) ----------------------

@dataclass
class Shot:
    beat_id: str  # must resolve to a real script beat
    description: str
    entities: list[str]


@dataclass
class Storyboard:
    shots: list[Shot]


def parse_storyboard(payload: str) -> Storyboard:
    obj = _extract_json(payload)
    raw_shots = obj.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise ProductionParseError("storyboard has no shots")
    shots: list[Shot] = []
    for i, rsh in enumerate(raw_shots):
        if not isinstance(rsh, dict):
            raise ProductionParseError(f"shot {i} is not an object")
        beat_id = str(rsh.get("beat_id", "")).strip()
        if not beat_id:
            raise ProductionParseError(f"shot {i} missing 'beat_id'")
        shots.append(Shot(beat_id=beat_id, description=str(rsh.get("description", "")).strip(),
                          entities=_str_list(rsh.get("entities"))))
    return Storyboard(shots=shots)
