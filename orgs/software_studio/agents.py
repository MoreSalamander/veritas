"""The cast — proposers. They produce artifacts; they decide nothing.

Phase 1 has two: the Spec agent (goal -> executable spec) and the Developer agent
(spec -> code). Both return PROPOSED artifacts. Whether those artifacts live or
die is entirely up to the gates.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from engine.model import ModelProvider
from orgs.software_studio.spec import SpecData

SPEC_SYSTEM = (
    "You are a precise software specification writer. Given a goal, respond with "
    "ONLY a JSON object — no prose, no markdown, no code fences. Schema: "
    '{"function_name": <valid python identifier>, "description": <string>, '
    '"signature": <string>, "cases": [{"args": [<positional args>], "expected": <value>}]}. '
    "Provide at least 3 concrete, correct input/output cases that fully pin the behavior."
)

DEV_SYSTEM = (
    "You are a careful Python developer. Given a JSON spec, respond with ONLY the "
    "Python source code that defines the function — no prose, no markdown fences, "
    "no tests, no example calls. The function must be named exactly as function_name "
    "and satisfy every case in the spec."
)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]  # drop opening ``` / ```python
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip() + "\n"
    return stripped + "\n" if not stripped.endswith("\n") else stripped


class SpecAgent:
    role = "spec"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, goal: str) -> Artifact:
        raw = self.provider.propose(
            role=self.role,
            prompt=f"Goal: {goal}",
            system=SPEC_SYSTEM,
        )
        return Artifact.propose(
            type="spec",
            owner="spec-agent",
            payload=raw,
            rationale=f"specification for goal: {goal}",
        )


class DeveloperAgent:
    role = "developer"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, spec: SpecData, parent_id: str) -> Artifact:
        spec_json = json.dumps(
            {
                "function_name": spec.function_name,
                "description": spec.description,
                "signature": spec.signature,
                "cases": [{"args": c.args, "expected": c.expected} for c in spec.cases],
            }
        )
        raw = self.provider.propose(
            role=self.role,
            prompt=f"Spec:\n{spec_json}",
            system=DEV_SYSTEM,
        )
        return Artifact.propose(
            type="code",
            owner="developer-agent",
            payload=_strip_code_fences(raw),
            rationale=f"implements {spec.function_name}()",
            parent_id=parent_id,
        )
