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

# The quote rules are the load-bearing part: a deterministic gate checks every
# provided quote as a contiguous span of the cited source, so the prompt states
# the exact contract — quotes are optional, exact-or-omitted, never decorated.
# This is coaching the proposer on the rules, not softening the gate.
RESEARCHER_SYSTEM = (
    "You are a careful researcher. You are given a topic and a set of SOURCES, each with an id "
    "and its text. Write a report as ONLY a JSON object — no prose, no markdown: "
    '{"topic": <string>, "claims": [{"text": <a factual claim>, "citations": '
    '[{"source": <a source id>, "quote": <optional: text copied verbatim from that source>}]}]}. '
    "Rules: EVERY claim must cite at least one source; use ONLY the given source ids; never "
    "invent a source, a quote, or a fact that isn't in the sources. "
    "QUOTES — read carefully, a machine checks every one: a quote is OPTIONAL. Include one only "
    "when you can copy a contiguous span character-for-character from the cited source's text. "
    "Never add labels, headings, colons, ellipses, bullet formatting, or any rewording of your "
    "own — the checker looks for your quote as an exact substring of the source, and one changed "
    "word fails the whole report. A short exact span (5-20 words) always beats a long "
    "approximation. If you are not certain the span appears exactly, omit the quote and keep the "
    "citation. Prefer fewer, well-grounded claims over many shaky ones."
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
            # Execution lineage (Stage 3): record WHICH model wrote this report,
            # not just that "the researcher" did. Not every provider names a
            # model (test doubles don't), so absent stays honest None.
            model=getattr(self.provider, "model", None),
        )
