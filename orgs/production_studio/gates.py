"""The Production Studio's gates — the verification model made executable.

The hard floor is structure + referential integrity + coverage: the concept is a usable spec, the
script uses only declared entities, the storyboard covers every beat and invents nothing. That is
exactly "consistency through verification." Duration is a soft quality signal (the narration's
runtime vs the concept's target) — advisory, never a block, because the target is a fuzzy intent,
not a hard contract (a platform-imposed limit could make it hard later).
"""

from __future__ import annotations

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from orgs.production_studio.production import (
    Concept,
    Script,
    ProductionParseError,
    concept_completeness,
    estimated_seconds,
    parse_concept,
    parse_script,
    parse_storyboard,
    script_beats,
    _norm,
)


class ConceptScorerGate(Gate):
    """HARD: the concept parses and is complete — otherwise there is no spec to verify against."""

    name = "concept-scorer"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            concept = parse_concept(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"concept not usable: {exc}")
        complete, missing = concept_completeness(concept)
        if not complete:
            return self._result(False, f"concept incomplete — missing: {', '.join(missing)}")
        return self._result(
            True, f"concept gateable: {len(concept.entities)} declared entit"
            f"{'y' if len(concept.entities) == 1 else 'ies'}, target {concept.target_seconds:g}s"
        )


class ScriptStructureGate(Gate):
    """HARD: the script parses into scenes and beats with narration — the structural floor."""

    name = "script-structure"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            script = parse_script(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"script not usable: {exc}")
        empty = [b.id for b in script_beats(script) if not b.narration]
        if empty:
            return self._result(False, f"beats with no narration: {', '.join(empty)}")
        n = len(script_beats(script))
        return self._result(True, f"{len(script.scenes)} scene(s), {n} beat(s), all narrated")


class ScriptGroundingGate(Gate):
    """HARD: every entity the script references was declared in the concept — no character or
    element appears that the concept did not authorize. This is the consistency guarantee."""

    name = "script-grounding"
    determinism = Determinism.HARD

    def __init__(self, concept: Concept) -> None:
        self.allowed = {_norm(e) for e in concept.entities}

    def check(self, artifact: Artifact) -> GateResult:
        try:
            script = parse_script(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"script not usable: {exc}")
        undeclared: dict[str, tuple[str, str]] = {}  # norm -> (name as written, first beat)
        for b in script_beats(script):
            for e in b.entities:
                if _norm(e) not in self.allowed and _norm(e) not in undeclared:
                    undeclared[_norm(e)] = (e, b.id)
        if undeclared:
            shown = ", ".join(f"{name} ({bid})" for name, bid in undeclared.values())
            return self._result(False, f"undeclared entit{'y' if len(undeclared) == 1 else 'ies'}: {shown}")
        return self._result(True, "every entity used was declared in the concept")


class DurationGate(Gate):
    """SOFT: the narration's estimated runtime is near the concept's target. Advisory — the target
    is an intent, not a contract; a gross over/undershoot is worth flagging, not blocking."""

    name = "duration"
    determinism = Determinism.SOFT

    def __init__(self, concept: Concept, tolerance: float = 0.5) -> None:
        self.target = concept.target_seconds
        self.tolerance = tolerance

    def check(self, artifact: Artifact) -> GateResult:
        try:
            est = estimated_seconds(parse_script(artifact.payload))
        except ProductionParseError as exc:
            return self._result(False, f"script not usable: {exc}")
        low, high = self.target * (1 - self.tolerance), self.target * (1 + self.tolerance)
        ok = low <= est <= high
        return self._result(
            ok, f"estimated narration {est:.1f}s vs target {self.target:g}s "
            f"(±{int(self.tolerance * 100)}% = {low:.0f}-{high:.0f}s)"
        )


class StoryboardCoverageGate(Gate):
    """HARD: every script beat has at least one shot — nothing in the script is dropped."""

    name = "coverage"
    determinism = Determinism.HARD

    def __init__(self, script: Script) -> None:
        self.beat_ids = [b.id for b in script_beats(script)]

    def check(self, artifact: Artifact) -> GateResult:
        try:
            board = parse_storyboard(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"storyboard not usable: {exc}")
        covered = {s.beat_id for s in board.shots}
        missing = [bid for bid in self.beat_ids if bid not in covered]
        if missing:
            return self._result(False, f"uncovered beat(s): {', '.join(missing)}")
        return self._result(True, f"all {len(self.beat_ids)} beat(s) covered by {len(board.shots)} shot(s)")


class StoryboardGroundingGate(Gate):
    """HARD: every shot references a real beat (no orphan shots), and shows only entities present
    in that beat (no characters invented at the visual stage). Referential integrity, downstream."""

    name = "storyboard-grounding"
    determinism = Determinism.HARD

    def __init__(self, script: Script) -> None:
        self.beat_entities = {b.id: {_norm(e) for e in b.entities} for b in script_beats(script)}

    def check(self, artifact: Artifact) -> GateResult:
        try:
            board = parse_storyboard(artifact.payload)
        except ProductionParseError as exc:
            return self._result(False, f"storyboard not usable: {exc}")
        orphans: list[str] = []
        invented: list[str] = []
        for i, s in enumerate(board.shots):
            if s.beat_id not in self.beat_entities:
                orphans.append(f"shot {i}->{s.beat_id}")
                continue
            for e in s.entities:
                if _norm(e) not in self.beat_entities[s.beat_id]:
                    invented.append(f"{e} in {s.beat_id}")
        problems = []
        if orphans:
            problems.append(f"orphan shot(s): {', '.join(orphans)}")
        if invented:
            problems.append(f"entit{'y' if len(invented) == 1 else 'ies'} not in the beat: {', '.join(invented)}")
        if problems:
            return self._result(False, "; ".join(problems))
        return self._result(True, "every shot anchors a real beat and shows only its entities")
