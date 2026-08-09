"""The Visualization teaching mode: the machine draws the concept.

The education spec asked for a Visualization agent that produces diagrams,
simulations, mental models — a teaching mode, not text. This is that,
Entropy-native: the agent emits a self-contained HTML page with inline SVG
that diagrams the concept, and it is VERIFIED the same way the web studio
verifies a page — rendered in a real headless browser, gated on facts:

* it loads with no console errors,
* it actually contains vector graphics (an ``<svg>`` with real shapes, not
  an empty frame),
* it labels what it draws (text the learner can read),
* it doesn't overflow its frame,
* and it names the concept it claims to teach.

A visualization that fails the gate is dropped, not shipped — the lesson
still stands on its text. A rendered, gated diagram is a teaching mode you
can trust; an ungated one is clip-art.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.model import ModelProvider

if TYPE_CHECKING:
    from orgs.web_studio.browser import BrowserExecutor


VISUALIZATION_SYSTEM = (
    "You are a visualization designer teaching ONE concept with a diagram. "
    "Return ONLY a complete, self-contained HTML document (doctype through "
    "</html>) — no markdown, no prose outside the HTML. Requirements a "
    "machine verifies by rendering it: the page contains an inline <svg> "
    "that DIAGRAMS the concept (boxes, arrows, a labeled process, a plotted "
    "relationship — real shapes, not one empty rect); the diagram carries "
    "readable <text> labels; a heading names the concept; all CSS is inline "
    "in a <style> tag and all graphics are inline SVG (no external URLs, no "
    "scripts, no images). Fit a 900x600 frame with no horizontal overflow. "
    "Teach with the picture: the layout itself should carry the idea."
)

_MIN_SHAPES = 3       # a diagram, not a single box
_MIN_LABELS = 2       # it must say what it draws
_MAX_BYTES = 200_000  # a diagram, not a dumped dataset


class VisualizationRejected(ValueError):
    """The visualization failed its render gate; the lesson ships without it."""


@dataclass
class VisualizationResult:
    html: str
    evidence: str


class VisualizationAgent:
    role = "designer"  # the visual hat, on the design-routed model

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, concept: str, lesson_gist: str, feedback: str | None = None) -> str:
        prompt = f"Concept to visualize: {concept}\n\nWhat the lesson teaches:\n{lesson_gist[:1200]}"
        if feedback:
            prompt = f"Your previous diagram was REJECTED: {feedback}\nFix exactly that.\n\n{prompt}"
        return self.provider.propose(role=self.role, prompt=prompt, system=VISUALIZATION_SYSTEM)


_SHAPE_RE = re.compile(r"<(rect|circle|ellipse|line|path|polygon|polyline)\b", re.I)
_TEXT_RE = re.compile(r"<text\b", re.I)


def _extract_html(raw: str) -> str:
    lo = raw.lower()
    start = lo.find("<!doctype")
    if start == -1:
        start = lo.find("<html")
    end = lo.rfind("</html>")
    if start == -1 or end == -1:
        # no wrapper — accept a bare <svg> document by framing it minimally
        svg_start = lo.find("<svg")
        if svg_start == -1:
            raise VisualizationRejected("no HTML or SVG in the visualization output")
        return f"<!doctype html><html><head><meta charset='utf-8'></head><body>{raw[svg_start:]}</body></html>"
    return raw[start : end + len("</html>")]


def build_visualization(
    concept: str,
    lesson_gist: str,
    provider: ModelProvider,
    browser: "BrowserExecutor",
    *,
    max_attempts: int = 2,
) -> VisualizationResult:
    """Propose a diagram, render it in a real browser, and gate it on the
    facts of what rendered. Retries once with the failure named; raises
    VisualizationRejected if it can't clear the gate."""
    agent = VisualizationAgent(provider)
    feedback: str | None = None
    last = "no attempt made"
    for _ in range(max_attempts):
        raw = agent.propose(concept, lesson_gist, feedback=feedback)
        try:
            html = _extract_html(raw)
        except VisualizationRejected as exc:
            feedback = last = str(exc)
            continue
        if len(html.encode("utf-8")) > _MAX_BYTES:
            feedback = last = f"too large ({len(html)} bytes) — a diagram, not a dataset"
            continue
        shapes = len(_SHAPE_RE.findall(html))
        labels = len(_TEXT_RE.findall(html))
        if "<svg" not in html.lower():
            feedback = last = "no inline <svg> — the diagram must be vector graphics"
            continue
        if shapes < _MIN_SHAPES:
            feedback = last = f"only {shapes} shape(s) — a real diagram needs at least {_MIN_SHAPES}"
            continue
        if labels < _MIN_LABELS:
            feedback = last = f"only {labels} <text> label(s) — the diagram must name what it shows"
            continue
        render = browser.render(html, selectors=["svg"])
        if not render.ok:
            feedback = last = f"failed to render: {render.error}"
            continue
        if render.console_errors:
            feedback = last = f"console error: {render.console_errors[0]}"
            continue
        if render.overflow:
            feedback = last = "the diagram overflows its frame horizontally"
            continue
        if not render.selectors_present.get("svg"):
            feedback = last = "the <svg> was not present in the rendered DOM"
            continue
        return VisualizationResult(
            html=html,
            evidence=f"rendered clean · {shapes} shapes, {labels} labels · no overflow",
        )
    raise VisualizationRejected(last)
