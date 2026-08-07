"""P14b — the Web Studio cast: proposers that produce a spec and a page. They decide
nothing; the browser-backed gates do.

The Designer turns a goal into the page's verifiable contract (which elements must exist).
The Web Developer turns that contract into a single self-contained HTML document. On
rejection it re-writes seeing the failing gates' evidence — the same self-correction the
software org has, but the feedback is "you overflow the viewport" instead of "case 3 failed."
"""

from __future__ import annotations

from engine.artifact import Artifact
from engine.model import ModelProvider
from orgs.software_studio.agents import _strip_code_fences
from orgs.web_studio.spec import PageSpec

DESIGNER_SYSTEM = (
    "You are a UI designer. Given a goal, respond with ONLY a JSON object — no prose, no "
    "fences. Schema: {\"title\": <string>, \"description\": <string>, \"required_elements\": "
    "[<CSS selector>, ...]}. required_elements is the page's VERIFIABLE contract: concrete "
    "selectors the page must contain, e.g. \"header\", \"nav\", \"h1\", \"#cta\", \"button\", "
    "\"form\", \"footer\". Provide 3-6 that capture the essential structure of the goal."
)

WEB_DEV_SYSTEM = (
    "You are a front-end developer. Given a page spec (JSON), respond with ONLY a complete, "
    "self-contained HTML document — inline CSS and JS, NO external resources (no CDN links, no "
    "external fonts/images; use inline SVG or data URIs if you need an image). It MUST: contain "
    "every selector in required_elements LITERALLY — if a selector names a tag like \"footer\" "
    "or \"nav\", use that semantic element (<footer>, <nav>, <main>, <header>), not a <div> "
    "styled to look like one; have EXACTLY ONE <h1>; give every <img> a "
    "non-empty alt attribute and every <button> visible text or an aria-label; never overflow "
    "horizontally at 1280px wide; and produce NO console errors. Output ONLY the HTML — no "
    "markdown fences, no commentary."
)


def _spec_to_json(spec: PageSpec) -> str:
    import json

    return json.dumps(
        {
            "title": spec.title,
            "description": spec.description,
            "required_elements": spec.required_elements,
        }
    )


class DesignerAgent:
    role = "designer"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(
        self, goal: str, lessons: str | None = None, feedback: str | None = None
    ) -> Artifact:
        prompt = f"Goal: {goal}"
        if feedback:
            prompt = (
                f"Your previous spec was REJECTED: {feedback}\n"
                f"Return a corrected spec that fixes exactly that.\n\n{prompt}"
            )
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=DESIGNER_SYSTEM)
        return Artifact.propose(
            type="page-spec",
            owner="designer-agent",
            payload=raw,
            rationale=f"page spec for goal: {goal}",
        )


class WebDeveloperAgent:
    role = "web-developer"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(
        self, spec: PageSpec, parent_id: str, lessons: str | None = None, feedback: str | None = None
    ) -> Artifact:
        prompt = f"Page spec:\n{_spec_to_json(spec)}"
        if feedback:
            prompt = (
                f"Your previous page was REJECTED by the checks: {feedback}\n"
                f"Fix exactly these problems and return the corrected full HTML.\n\n{prompt}"
            )
        if lessons:
            prompt = f"{lessons}\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=WEB_DEV_SYSTEM)
        return Artifact.propose(
            type="page",
            owner="web-developer-agent",
            payload=_strip_code_fences(raw),
            rationale=f"page for: {spec.title or spec.description}",
            parent_id=parent_id,
        )


BRIEF_SYSTEM = (
    "You are a UX researcher decomposing a website request into a design "
    'brief. Produce ONLY a JSON object: {"industry": <short phrase>, '
    '"audience": [<who this site must convince>], "brand_qualities": '
    '[<what the brand must communicate>], "user_goals": [<what the owner '
    'needs the site to achieve>], "pages": [<page types>], "design_intents": '
    "[<semantic phrases a design researcher would hunt with, e.g. "
    "'medical trust', 'enterprise credibility'>]}. "
    "Pages MUST come from this exact vocabulary (2-5 pages, pick what the "
    "request truly needs; never invent a type): {pages}."
)


class BriefAgent:
    """Phase 1: user intent -> design brief; parse_design_brief decides."""

    role = "designer"

    def __init__(self, provider) -> None:
        self.provider = provider

    def propose(self, goal: str, feedback: str | None = None) -> str:
        from orgs.web_studio.design_intelligence import PAGE_TYPES

        prompt = f"Website request: {goal}"
        if feedback:
            prompt = f"Your previous brief was REJECTED: {feedback}\nFix exactly that.\n\n{prompt}"
        return self.provider.propose(
            role=self.role, prompt=prompt,
            system=BRIEF_SYSTEM.replace("{pages}", ", ".join(sorted(PAGE_TYPES))),
        )


SYNTHESIS_SYSTEM = (
    "You are a design director synthesizing a NEW design system from research "
    "— never copying. You are given a design brief and a corpus of design "
    "SOURCES, each with an id. Produce ONLY a JSON object: "
    '{"layout": <one of {layouts}>, '
    '"palette": {"bg": <#rrggbb>, "surface": <#rrggbb>, "ink": <#rrggbb>, '
    '"accent": <#rrggbb>}, "heading_font": <CSS font stack>, '
    '"body_font": <CSS font stack>, "components_by_page": {<page>: '
    "[<components from: {components}>]}, "
    '"inspired_by": [{"source": <a source id from the corpus>, "pattern": '
    "<the specific pattern you are drawing from it>}], "
    '"rationale": <one sentence>}. '
    "Every page in the brief must appear in components_by_page. Every "
    "inspired_by MUST cite a real source id — an influence that cannot name "
    "its source will be refused by a machine. Contrast matters: ink must "
    "read clearly on bg and surface."
)


class SynthesisAgent:
    """Phase 5: brief + design corpus -> a design system with provenance."""

    role = "designer"

    def __init__(self, provider) -> None:
        self.provider = provider

    def propose(self, brief_text: str, corpus_text: str, feedback: str | None = None) -> str:
        from orgs.web_studio.design_intelligence import COMPONENTS, LAYOUTS

        prompt = f"{brief_text}\n\nDESIGN CORPUS:\n{corpus_text}"
        if feedback:
            prompt = f"Your previous design system was REJECTED: {feedback}\nFix exactly that.\n\n{prompt}"
        system = (SYNTHESIS_SYSTEM
                  .replace("{layouts}", ", ".join(LAYOUTS))
                  .replace("{components}", ", ".join(sorted(COMPONENTS))))
        return self.provider.propose(role=self.role, prompt=prompt, system=system)
