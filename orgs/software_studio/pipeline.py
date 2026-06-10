"""The Software Studio run: goal -> spec -> code, gated at every boundary.

One Run walks the whole job so the activity log and memory are unified. The spec
must be accepted (executable) before the developer is ever asked to write code —
if the spec is rejected, the run ends there and the developer never runs. That
ordering is the doctrine: no synthesis before the constraints are real.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.memory import MemoryStore
from engine.model import ModelProvider
from engine.run import Outcome, Run
from orgs.software_studio.agents import DeveloperAgent, SpecAgent
from orgs.software_studio.gates import AcceptanceGate, SpecScorerGate, SyntaxGate
from orgs.software_studio.spec import parse_spec


@dataclass
class StudioResult:
    spec_outcome: Outcome
    code_outcome: Outcome | None  # None when the spec was rejected first
    accepted: bool


def build_function(goal: str, provider: ModelProvider, memory: MemoryStore) -> StudioResult:
    run = Run(goal=goal, memory=memory)

    # EXPLAIN — propose a spec, gate it for executability.
    spec_artifact = SpecAgent(provider).propose(goal)
    spec_outcome = run.submit(spec_artifact, [SpecScorerGate()])
    if not spec_outcome.accepted:
        return StudioResult(spec_outcome=spec_outcome, code_outcome=None, accepted=False)

    # SYNTHESIZE — only now, against an accepted spec, write code; gate it hard.
    spec = parse_spec(spec_artifact.payload)
    code_artifact = DeveloperAgent(provider).propose(spec, parent_id=spec_artifact.id)
    code_outcome = run.submit(
        code_artifact,
        [SyntaxGate(spec.function_name), AcceptanceGate(spec)],
    )
    return StudioResult(
        spec_outcome=spec_outcome,
        code_outcome=code_outcome,
        accepted=code_outcome.accepted,
    )
