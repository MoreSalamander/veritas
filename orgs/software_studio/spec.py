"""The Spec — the load-bearing object of a software run.

We do not accept prose requirements. We accept a spec whose acceptance criteria
are *executable* — concrete input/expected cases that compile straight into
assertions. A spec the scorer can't turn into tests is rejected before a single
line of code is written. This is the myAIscript "pass-a-score" move, generalized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_PY_BLOCK = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.DOTALL)


def extract_python_blocks(markdown: str) -> list[str]:
    """Pull the fenced ```python blocks out of a markdown document — used by the
    doc agent's examples-run gate to verify documentation examples actually run."""
    return [m.group(1) for m in _PY_BLOCK.finditer(markdown)]


class SpecParseError(ValueError):
    """The proposed spec is not executable. The spec-scorer rejects on this."""


@dataclass
class Case:
    args: list[Any]
    expected: Any


@dataclass
class SpecData:
    function_name: str
    description: str
    signature: str
    cases: list[Case]


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise SpecParseError("no JSON object found in spec output")
    return text[start : end + 1]


def parse_spec(payload: str) -> SpecData:
    """Parse + validate a proposed spec. Raises SpecParseError if it isn't
    executable — which is exactly how the spec-scorer gate bites on a bad
    proposal (prose, missing cases, malformed cases)."""
    import json

    try:
        obj: Any = json.loads(_extract_json(payload))
    except (ValueError, TypeError) as exc:
        raise SpecParseError(f"spec is not valid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise SpecParseError("spec must be a JSON object")

    name = obj.get("function_name")
    if not isinstance(name, str) or not name.isidentifier():
        raise SpecParseError("function_name missing or not a valid identifier")

    raw_cases = obj.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise SpecParseError("spec has no acceptance cases (nothing to verify against)")

    cases: list[Case] = []
    for index, case in enumerate(raw_cases):
        if not isinstance(case, dict) or "args" not in case or "expected" not in case:
            raise SpecParseError(f"case {index} missing 'args' or 'expected'")
        if not isinstance(case["args"], list):
            raise SpecParseError(f"case {index} 'args' must be a list")
        cases.append(Case(args=case["args"], expected=case["expected"]))

    return SpecData(
        function_name=name,
        description=str(obj.get("description", "")),
        signature=str(obj.get("signature", "")),
        cases=cases,
    )
