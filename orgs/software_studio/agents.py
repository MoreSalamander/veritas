"""The cast — proposers. They produce artifacts; they decide nothing.

Phase 1 has two: the Spec agent (goal -> executable spec) and the Developer agent
(spec -> code). Both return PROPOSED artifacts. Whether those artifacts live or
die is entirely up to the gates.
"""

from __future__ import annotations

import json
from typing import Any

from engine.artifact import Artifact
from engine.model import ModelProvider
from orgs.software_studio.spec import SpecData

SPEC_SYSTEM = (
    "You are a precise software specification writer. Given a goal, respond with "
    "ONLY a JSON object — no prose, no markdown, no code fences. Schema: "
    '{"function_name": <valid python identifier>, "description": <string>, '
    '"signature": <string>, "cases": [{"args": [<positional args>], "expected": <value>}], '
    '"properties": [<oracle-free relation>]}. '
    "Provide at least 3 concrete input/output cases. ALSO provide 'properties': "
    "relations that must hold REGARDLESS of the exact output — these are how the system "
    "verifies you WITHOUT trusting your numbers, so provide them whenever they apply. "
    "Each property is one of: "
    '{"kind":"monotonic","direction":"increasing"|"decreasing","inputs":[[x1],[x2],...]} '
    "(inputs listed in that order; outputs must follow it); "
    '{"kind":"invariant","invariant":<one of '
    "sorted_ascending|sorted_descending|is_permutation_of_input|length_preserved|"
    'elements_unique|non_negative>,"inputs":[[<arg>],...]}; '
    '{"kind":"idempotent","inputs":[[x],...]} (f(f(x))==f(x)); '
    '{"kind":"round_trip","inverse":<other function name>,"inputs":[[x],...]} '
    "(only if an inverse function exists in the same build). Omit 'properties' (or use []) "
    "only when no such relation applies."
)

DEV_SYSTEM = (
    "You are a careful Python developer. Given a JSON spec, respond with ONLY the "
    "Python source code that defines the function — no prose, no markdown fences, "
    "no tests, no example calls. The function must be named exactly as function_name "
    "and satisfy every case in the spec."
)

QA_SYSTEM = (
    "You are an independent QA engineer. Given a spec, propose 2-3 ADDITIONAL "
    "edge-case tests the examples might miss (boundaries, empties, negatives, large "
    "inputs). Respond with ONLY a JSON array — no prose, no markdown: "
    '[{"args": [<positional args>], "expected": <value>}].'
)


def _spec_to_json(spec: SpecData) -> str:
    return json.dumps(
        {
            "function_name": spec.function_name,
            "description": spec.description,
            "signature": spec.signature,
            "cases": [{"args": c.args, "expected": c.expected} for c in spec.cases],
            "properties": [p.to_payload() for p in spec.properties],
        }
    )


def _parse_cases(text: str) -> list[dict[str, Any]]:
    """Best-effort parse of a proposed JSON array of cases. Returns [] on anything
    malformed — QA is advisory, so unusable output simply yields no findings."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        arr = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(arr, list):
        return []
    cases: list[dict[str, Any]] = []
    for case in arr:
        if isinstance(case, dict) and isinstance(case.get("args"), list) and "expected" in case:
            cases.append({"args": case["args"], "expected": case["expected"]})
    return cases


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

    def propose(self, goal: str, lessons: str | None = None) -> Artifact:
        prompt = f"Goal: {goal}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=SPEC_SYSTEM)
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

    def propose(
        self, spec: SpecData, parent_id: str, lessons: str | None = None, feedback: str | None = None
    ) -> Artifact:
        prompt = f"Spec:\n{_spec_to_json(spec)}"
        if feedback:
            prompt = (
                f"Your previous attempt was REJECTED by the checks: {feedback}\n"
                f"Fix exactly these problems and return corrected code.\n\n{prompt}"
            )
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=DEV_SYSTEM)
        return Artifact.propose(
            type="code",
            owner="developer-agent",
            payload=_strip_code_fences(raw),
            rationale=f"implements {spec.function_name}()",
            parent_id=parent_id,
        )


class QAAgent:
    role = "qa"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose_cases(self, spec: SpecData) -> list[dict[str, Any]]:
        """Independent tests written from the SPEC (not the code), so QA never sees
        the implementation it reviews."""
        raw = self.provider.propose(
            role=self.role,
            prompt=f"Spec:\n{_spec_to_json(spec)}",
            system=QA_SYSTEM,
        )
        return _parse_cases(raw)


DOC_SYSTEM = (
    "You are a technical writer documenting a single Python function that already "
    "exists and is correct. Write a short Markdown doc: one or two sentences on what "
    "it does, then at least one fenced ```python example that CALLS the function and "
    "asserts or prints a result. The function is ALREADY DEFINED in the environment — "
    "do NOT redefine it, just call it by name. Output ONLY the Markdown."
)


class DocAgent:
    """The Documentation role — a software-org agent, not a separate org. It
    documents the accepted function; its examples are verified to run against the
    real implementation (same verification model as the code: execute it)."""

    role = "doc"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(
        self, spec: SpecData, code: str, parent_id: str, lessons: str | None = None
    ) -> Artifact:
        prompt = f"Function name: {spec.function_name}\nImplementation:\n{code}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=DOC_SYSTEM)
        return Artifact.propose(
            type="documentation",
            owner="doc-agent",
            payload=raw,
            rationale=f"documentation for {spec.function_name}()",
            parent_id=parent_id,
        )
