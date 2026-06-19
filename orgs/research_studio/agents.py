"""P16b — the Research Studio cast: a Researcher that grounds every claim in the sources.

The Researcher is given a topic and a pinned corpus, and proposes a report whose every claim
cites a source and quotes it verbatim. It decides nothing — the grounding gates do. On
rejection it re-writes seeing the failing gate's evidence ("misquote of src1: ..."), the same
self-correction the other orgs have, aimed at grounding instead of execution.
"""

from __future__ import annotations

from engine.artifact import Artifact
from engine.model import ModelProvider
from orgs.research_studio.report import Corpus

RESEARCHER_SYSTEM = (
    "You are a careful researcher. You are given a topic and a set of SOURCES, each with an id "
    "and its text. Write a report as ONLY a JSON object — no prose, no markdown: "
    '{"topic": <string>, "claims": [{"text": <a factual claim>, "citations": '
    '[{"source": <a source id>, "quote": <text copied VERBATIM from that source>}]}]}. '
    "Rules: EVERY claim must cite at least one source; EVERY quote must be copied exactly from "
    "the cited source's text; use ONLY the given source ids; never invent a source, a quote, or "
    "a fact that isn't in the sources. Prefer fewer, well-grounded claims over many shaky ones."
)


def corpus_prompt(topic: str, corpus: Corpus) -> str:
    # Present the id plainly (no brackets/punctuation the model might copy into the citation —
    # a citation must equal the id exactly to resolve).
    sources = "\n\n".join(f"source id: {sid}\ntext: {text}" for sid, text in corpus.items())
    return f"Topic: {topic}\n\nSOURCES (cite the source id exactly as written):\n{sources}"


class ResearcherAgent:
    role = "researcher"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(
        self, topic: str, corpus: Corpus, lessons: str | None = None, feedback: str | None = None
    ) -> Artifact:
        prompt = corpus_prompt(topic, corpus)
        if feedback:
            prompt = (
                f"Your previous report was REJECTED: {feedback}\n"
                f"Fix exactly that and return the corrected report.\n\n{prompt}"
            )
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=RESEARCHER_SYSTEM)
        return Artifact.propose(
            type="report",
            owner="researcher-agent",
            payload=raw,
            rationale=f"grounded report on: {topic}",
        )
