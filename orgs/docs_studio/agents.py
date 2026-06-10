"""The docs cast — proposers. They write; the gates decide.

Outline agent (topic -> structured outline) and Writer agent (outline -> a markdown
explainer with self-contained, runnable examples).
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from engine.model import ModelProvider
from orgs.docs_studio.spec import DocsSpec

OUTLINE_SYSTEM = (
    "You are a technical documentation planner. Given a topic, respond with ONLY a "
    "JSON object — no prose, no markdown, no code fences. Schema: "
    '{"title": <string>, "sections": [<section heading strings>], "min_examples": <int >= 1>}. '
    "Plan a short explainer that will include at least min_examples runnable Python examples."
)

WRITER_SYSTEM = (
    "You are a precise technical writer. Given a JSON outline, write a concise explainer "
    "in GitHub-flavored Markdown. Use each outline section as a `##` heading. Include at "
    "least min_examples fenced ```python code blocks. CRITICAL: every code block must be "
    "COMPLETELY SELF-CONTAINED and run without error on its own — include all imports, "
    "define every name it uses, and end with an assert or print that demonstrates it works. "
    "Do not reference variables from earlier blocks. Output ONLY the Markdown document."
)


def _outline_to_json(spec: DocsSpec) -> str:
    return json.dumps(
        {"title": spec.title, "sections": spec.sections, "min_examples": spec.min_examples}
    )


class OutlineAgent:
    role = "outline"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, topic: str, lessons: str | None = None) -> Artifact:
        prompt = f"Topic: {topic}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=OUTLINE_SYSTEM)
        return Artifact.propose(
            type="docs-outline",
            owner="outline-agent",
            payload=raw,
            rationale=f"outline for topic: {topic}",
        )


class WriterAgent:
    role = "writer"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, spec: DocsSpec, parent_id: str, lessons: str | None = None) -> Artifact:
        prompt = f"Outline:\n{_outline_to_json(spec)}"
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=WRITER_SYSTEM)
        return Artifact.propose(
            type="document",
            owner="writer-agent",
            payload=raw,
            rationale=f"document: {spec.title}",
            parent_id=parent_id,
        )
