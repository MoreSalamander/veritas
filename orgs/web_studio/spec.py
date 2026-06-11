"""P14b — the page spec: a UI's executable contract.

We don't accept "make it look nice." We accept a spec that names the elements the page MUST
contain — concrete CSS selectors the StructureGate checks against the real rendered DOM. That
list is the front-end analogue of the software spec's cases: the part of "done" that is a fact,
not a taste. Aesthetics are deliberately absent here; they're soft, and they live elsewhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate


class PageSpecParseError(ValueError):
    """The proposed page spec is not usable. PageSpecGate rejects on this."""


@dataclass
class PageSpec:
    title: str
    description: str
    required_elements: list[str]  # CSS selectors the rendered page must contain


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise PageSpecParseError("no JSON object found in spec output")
    return text[start : end + 1]


def parse_page_spec(payload: str) -> PageSpec:
    try:
        obj: Any = json.loads(_extract_json(payload))
    except (ValueError, TypeError) as exc:
        raise PageSpecParseError(f"spec is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise PageSpecParseError("spec must be a JSON object")

    raw = obj.get("required_elements")
    if not isinstance(raw, list) or not raw:
        raise PageSpecParseError("spec has no required_elements (nothing to verify against)")
    elements: list[str] = []
    for i, sel in enumerate(raw):
        if not isinstance(sel, str) or not sel.strip():
            raise PageSpecParseError(f"required_elements[{i}] is not a usable selector")
        elements.append(sel.strip())

    return PageSpec(
        title=str(obj.get("title", "")),
        description=str(obj.get("description", "")),
        required_elements=elements,
    )


class PageSpecGate(Gate):
    """The spec must name what the page must contain — otherwise there is nothing to verify."""

    name = "page-spec"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            spec = parse_page_spec(artifact.payload)
        except PageSpecParseError as exc:
            return self._result(False, f"spec not usable: {exc}")
        return self._result(
            True, f"{len(spec.required_elements)} required element(s) pin the page"
        )
