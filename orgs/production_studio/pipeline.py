"""The Production Studio run: a brief becomes a verified concept -> script -> storyboard chain.

Same spine as every other org; only the cast and the verification model changed. Each stage is
proposed, gated, and self-corrects on rejection (run.attempt). The chain is strict: a stage that
can't pass stops the production — you never get a storyboard for a script that referenced an
undeclared character, because the script never shipped. The downstream gates take the accepted
upstream artifact so consistency is checked across the boundary, not just within a stage.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from engine.artifact import Artifact
from engine.memory import MemoryStore, format_lessons
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.production_studio.agents import (
    ConceptAgent,
    ScriptwriterAgent,
    StoryboardArtistAgent,
)
from orgs.production_studio.assets import (
    AssetConsistencyGate,
    AssetCoverageGate,
    AssetGenerator,
    AssetGeneratorAgent,
    AssetIntegrityGate,
    parse_assets,
)
from orgs.production_studio.editing import (
    EditorAgent,
    SequenceCoverageGate,
    TimelineIntegrityGate,
)
from orgs.production_studio.gates import (
    ConceptScorerGate,
    DurationGate,
    ScriptGroundingGate,
    ScriptStructureGate,
    StoryboardCoverageGate,
    StoryboardGroundingGate,
)
from orgs.production_studio.production import parse_concept, parse_script, parse_storyboard


@dataclass
class ProductionResult:
    outcomes: list[Outcome]  # concept, then script, then storyboard — fewer if it stopped early
    accepted: bool  # the whole chain shipped
    informed_by: list[str] = field(default_factory=list)
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def build_production(
    brief: str, provider: ModelProvider, memory: MemoryStore,
    asset_generator: AssetGenerator | None = None, asset_dir: Path | None = None,
) -> ProductionResult:
    run = Run(goal=brief, memory=memory)
    recalled = memory.recall(brief, categories=["failure", "lesson", "decision"], limit=3)
    lessons = format_lessons(recalled) or ""
    informed_by = [r.id for r in recalled]
    outcomes: list[Outcome] = []

    def _stamp(art: Artifact) -> Artifact:
        art.provenance.informed_by.extend(informed_by)
        return art

    # Stage 1 — the concept (the root spec everything traces back to)
    concept_out = run.attempt(
        lambda fb: _stamp(ConceptAgent(provider).propose(brief, lessons, fb)),
        [ConceptScorerGate(), ValidationGate()],
    )
    outcomes.append(concept_out)
    if not concept_out.accepted:
        return ProductionResult(outcomes, False, informed_by, run.id, list(run.log))
    concept = parse_concept(concept_out.artifact.payload)

    # Stage 2 — the script (grounded in the concept's declared entities)
    script_out = run.attempt(
        lambda fb: _stamp(ScriptwriterAgent(provider).propose(concept, lessons, fb)),
        [ScriptStructureGate(), ScriptGroundingGate(concept), DurationGate(concept), ValidationGate()],
    )
    outcomes.append(script_out)
    if not script_out.accepted:
        return ProductionResult(outcomes, False, informed_by, run.id, list(run.log))
    script = parse_script(script_out.artifact.payload)

    # Stage 3 — the storyboard (covers every beat, invents nothing)
    board_out = run.attempt(
        lambda fb: _stamp(StoryboardArtistAgent(provider).propose(concept, script, fb)),
        [StoryboardCoverageGate(script), StoryboardGroundingGate(script), ValidationGate()],
    )
    outcomes.append(board_out)
    if not board_out.accepted or asset_generator is None:
        return ProductionResult(outcomes, board_out.accepted, informed_by, run.id, list(run.log))
    storyboard = parse_storyboard(board_out.artifact.payload)

    # Stage 4 (P25b) — assets: real media per shot/beat, verified by coverage + integrity. This is
    # a tool call, not a model proposal, so it runs once (run.submit) rather than self-correcting.
    out_dir = asset_dir or Path(tempfile.mkdtemp(prefix="veritas_assets_"))
    asset_art = _stamp(AssetGeneratorAgent(asset_generator).propose(script, storyboard, out_dir))
    asset_out = run.submit(
        asset_art,
        [AssetCoverageGate(script, storyboard), AssetIntegrityGate(),
         AssetConsistencyGate(), ValidationGate()],
    )
    outcomes.append(asset_out)
    if not asset_out.accepted:
        return ProductionResult(outcomes, False, informed_by, run.id, list(run.log))
    assets = parse_assets(asset_out.artifact.payload)

    # Stage 5 (P25d) — editing: lay the shots + narration into a verified timeline.
    edit_art = _stamp(EditorAgent().propose(storyboard, assets))
    edit_out = run.submit(
        edit_art,
        [SequenceCoverageGate(storyboard), TimelineIntegrityGate(assets), ValidationGate()],
    )
    outcomes.append(edit_out)
    return ProductionResult(outcomes, edit_out.accepted, informed_by, run.id, list(run.log))
