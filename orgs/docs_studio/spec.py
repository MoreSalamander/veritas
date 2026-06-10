"""The docs contract — the executable acceptance criteria for a document.

The software studio's spec pins behavior with runnable cases. The docs studio's spec
pins a document with required sections and a floor of *runnable* examples. The
load-bearing idea is the same: the artifact is only acceptable if it can be checked
by machine — here, by actually executing the examples it contains.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_PY_BLOCK = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.DOTALL)


class DocsSpecParseError(ValueError):
    """The proposed outline is not usable. The outline-scorer rejects on this."""


@dataclass
class DocsSpec:
    title: str
    sections: list[str]
    min_examples: int


def extract_python_blocks(markdown: str) -> list[str]:
    return [m.group(1) for m in _PY_BLOCK.finditer(markdown)]


def strip_code_blocks(markdown: str) -> str:
    return _PY_BLOCK.sub("", markdown)


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise DocsSpecParseError("no JSON object found in outline output")
    return text[start : end + 1]


def parse_docs_spec(payload: str) -> DocsSpec:
    try:
        obj: Any = json.loads(_extract_json(payload))
    except (ValueError, TypeError) as exc:
        raise DocsSpecParseError(f"outline is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise DocsSpecParseError("outline must be a JSON object")

    title = obj.get("title")
    if not isinstance(title, str) or not title.strip():
        raise DocsSpecParseError("missing title")

    sections = obj.get("sections")
    if not isinstance(sections, list) or not sections or not all(isinstance(s, str) for s in sections):
        raise DocsSpecParseError("sections must be a non-empty list of strings")

    min_examples = obj.get("min_examples", 1)
    if not isinstance(min_examples, int) or min_examples < 1:
        raise DocsSpecParseError("min_examples must be an integer >= 1")

    return DocsSpec(title=title, sections=list(sections), min_examples=min_examples)
