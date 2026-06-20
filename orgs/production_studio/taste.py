"""P25f — the taste tier: create mode for a production. The human is the gate for feel.

The whole P25 chain (concept → script → storyboard → assets → timeline → publish) is the machine
floor: it proves the production is *consistent and intact*, never that it's *good*. Goodness has no
oracle but your sign-off, so create mode adds the third trust tier on top — a human approves the
finished cut. An approval is recorded as a human-approved memory record and folded into a production
style profile (tone, resolution, length) that seeds the next brief, so the system learns YOUR style.
A request for changes amends the brief and the production re-runs. This is where the "QA" role lives:
QA is the gate layer (every P25 gate) plus the human sign-off — never a separate proposer.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.memory import MemoryRecord, MemoryStore
from engine.model import ModelProvider
from orgs.production_studio.assets import AssetGenerator
from orgs.production_studio.pipeline import ProductionResult, build_production
from orgs.production_studio.production import Concept, parse_concept
from orgs.production_studio.publishing import (
    Publisher,
    PublishProfile,
    parse_publish,
)


@dataclass
class Review:
    """A human's verdict on the finished production. approved=False carries feedback to iterate on."""

    approved: bool
    feedback: str = ""


ReviewFn = Callable[[ProductionResult], Review]


# --- the production style profile (learns YOUR style from sign-offs) ----------------------

@dataclass
class ProductionProfile:
    approvals: int = 0
    tone_votes: dict[str, int] = field(default_factory=dict)
    resolution_votes: dict[str, int] = field(default_factory=dict)
    target_seconds: list[float] = field(default_factory=list)

    def update(self, concept: Concept, profile: PublishProfile | None) -> None:
        self.approvals += 1
        if concept.tone:
            self.tone_votes[concept.tone] = self.tone_votes.get(concept.tone, 0) + 1
        if concept.target_seconds > 0:
            self.target_seconds.append(concept.target_seconds)
        if profile is not None:
            key = f"{profile.width}x{profile.height}"
            self.resolution_votes[key] = self.resolution_votes.get(key, 0) + 1

    def _top(self, votes: dict[str, int]) -> str | None:
        return max(votes, key=lambda k: votes[k]) if votes else None

    def hint(self) -> str | None:
        if self.approvals == 0:
            return None
        parts = []
        if self._top(self.tone_votes):
            parts.append(f"tone {self._top(self.tone_votes)}")
        if self._top(self.resolution_votes):
            parts.append(f"resolution {self._top(self.resolution_votes)}")
        if self.target_seconds:
            parts.append(f"~{round(sum(self.target_seconds) / len(self.target_seconds))}s long")
        return "; ".join(parts) if parts else None


class ProductionProfileStore:
    """File-per-profile, mirroring the web aesthetic profile; a DB can slot behind it when hosted."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> ProductionProfile:
        if not self.path.exists():
            return ProductionProfile()
        d: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return ProductionProfile(
            approvals=int(d.get("approvals", 0)),
            tone_votes=dict(d.get("tone_votes", {})),
            resolution_votes=dict(d.get("resolution_votes", {})),
            target_seconds=list(d.get("target_seconds", [])),
        )

    def save(self, profile: ProductionProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")


# --- the create-mode build loop -----------------------------------------------------------

@dataclass
class CreateProductionResult:
    accepted: bool  # human-approved (and necessarily machine-verified first)
    machine_verified: bool  # the whole chain shipped on at least one attempt
    production: ProductionResult | None  # the most recent run
    iterations: int
    run_id: str = ""
    memory_path: str = ""  # the human-approved record (empty if never approved)


def _output_of(result: ProductionResult) -> str:
    last = result.outcomes[-1].artifact
    if last.type == "publish":
        try:
            return parse_publish(last.payload).output
        except Exception:
            return ""
    return "(unpublished cut)"


def build_create_production(
    brief: str, provider: ModelProvider, memory: MemoryStore, review: ReviewFn,
    asset_generator: AssetGenerator | None = None, publisher: Publisher | None = None,
    profile: PublishProfile | None = None, asset_dir: Path | None = None,
    profile_store: ProductionProfileStore | None = None, max_attempts: int = 2,
) -> CreateProductionResult:
    """Run the production to the machine floor; if it ships, the human judges the residue. Approve →
    human-approved record + the style profile compounds. Request changes → the feedback amends the
    brief and it re-runs. Only a human approval 'ships' a production in create mode."""
    hint = profile_store.load().hint() if profile_store else None
    brief_now = f"{brief}\n\nThe creator's usual style: {hint}." if hint else brief
    machine_verified = False
    last: ProductionResult | None = None

    for attempt in range(1, max_attempts + 1):
        result = build_production(
            brief_now, provider, memory, asset_generator=asset_generator,
            asset_dir=asset_dir, publisher=publisher, profile=profile,
        )
        last = result
        if not result.accepted:  # a machine gate refused — never reaches the human
            return CreateProductionResult(False, machine_verified, result, attempt, result.run_id)
        machine_verified = True

        verdict = review(result)
        if verdict.approved:
            concept = parse_concept(result.outcomes[0].artifact.payload)
            record = MemoryRecord(
                category="decision",
                title=f"human-approved production: {concept.title or brief[:40]}",
                body=f"Approved by the human after the full chain passed.\n\noutput: {_output_of(result)}",
                tags=["production", "human-approved"],
                provenance={"run_id": result.run_id, "output": _output_of(result),
                            "approved_by": "human"},
            )
            path = memory.persist(record)
            if profile_store is not None:  # the approval teaches the style profile (it compounds)
                prof = profile_store.load()
                prof.update(concept, profile)
                profile_store.save(prof)
            return CreateProductionResult(True, True, result, attempt, result.run_id, str(path))

        brief_now = f"{brief}\n\nRevision requested by the reviewer: {verdict.feedback}"

    return CreateProductionResult(False, True, last, max_attempts,
                                  last.run_id if last else "")
