"""The site build: the design agency assembling a whole website.

Flow — every arrow with a deterministic contract or a gate on it:

    goal -> DesignBrief (parse-refused vocab)
         -> parallel design corpus (shared fan-out)
         -> DesignSystem (synthesis with provenance, parse-refused)
         -> one page build per brief page, through the EXISTING per-page
            wall (spec, render, structure, a11y, aesthetics), with the
            design system injected as hard constraints
         -> SITE gates, new and deterministic:
              nav-links-resolve   every page's nav reaches every page
              system-consistency  every page carries the system's palette
                                  variables and heading font
         -> one repair round for pages that break a site gate, then the
            verdict stands.

A site is REFUSED unless every page passed its wall AND the site gates
hold. Verified design knowledge (layout, patterns, influences) persists to
org memory, so the next project starts briefed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from engine.memory import MemoryRecord, MemoryStore
from engine.model import ModelProvider
from orgs.web_studio.agents import BriefAgent, SynthesisAgent
from orgs.web_studio.design_intelligence import (
    COMPONENTS,
    BriefParseError,
    DesignBrief,
    DesignSystem,
    DesignSystemParseError,
    acquire_design_corpus,
    parse_design_brief,
    parse_design_system,
)
from orgs.web_studio.pipeline import PageResult, build_page

if TYPE_CHECKING:
    from commons.parallel_client import SearchClient
    from orgs.research_studio.intelligence import AcquiredSource


class SiteBriefRejected(ValueError):
    """The brief failed its contract twice — the honest end of the run."""


class SiteSynthesisRejected(ValueError):
    """The design system failed its contract twice."""


@dataclass
class SiteGateResult:
    gate: str
    passed: bool
    evidence: str


@dataclass
class SiteResult:
    """The whole project: what was asked, researched, synthesized, built,
    and how the wall ruled on each piece."""

    goal: str
    brief: DesignBrief
    system: DesignSystem
    sources: list["AcquiredSource"]
    pages: dict[str, PageResult]
    site_gates: list[SiteGateResult]
    accepted: bool
    context_graph: dict = field(default_factory=dict)

    def page_html(self, slug: str) -> str:
        result = self.pages.get(slug)
        art = getattr(getattr(result, "page_outcome", None), "artifact", None)
        return getattr(art, "payload", "") or ""


def _page_goal(page: str, brief: DesignBrief, system: DesignSystem, extra: str = "") -> str:
    """The per-page build order: the page's charter plus the design system
    as HARD constraints the page pipeline must satisfy."""
    from orgs.web_studio.design_intelligence import PAGE_TYPES

    comps = system.components_by_page[page]
    selectors = sorted({sel for c in comps for sel in COMPONENTS[c]})
    others = [p for p in brief.pages if p != page]
    nav_links = ", ".join(f'{p} -> href="{p}.html"' for p in brief.pages)
    lines = [
        f"Build the {page.upper()} page ({PAGE_TYPES[page]}) of a {len(brief.pages)}-page site: {brief.goal}.",
        f"Audience: {', '.join(brief.audience) or 'general'}. "
        f"The brand must communicate: {', '.join(brief.brand_qualities) or 'clarity'}.",
        "HARD CONSTRAINTS a machine will verify:",
        f"- Include these components: {', '.join(comps)} (matching selectors: {'; '.join(selectors)}).",
        f"- Start the <style> with EXACTLY this variable block: {system.css_variables()}",
        "- Use ONLY var(--bg), var(--surface), var(--ink), var(--accent) (and any other declared "
        "variables) for colors.",
        f"- Headings font-family: {system.heading_font}; body font-family: {system.body_font}.",
        f"- A <nav> present on the page linking every page of the site: {nav_links} "
        f"(this page is {page}.html; link the other {len(others)} too).",
        f"- Layout style: {system.layout.replace('_', ' ')}.",
    ]
    if system.rationale:
        lines.append(f"Design rationale to honor: {system.rationale}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


_HREF = re.compile(r'href="([^"]+)"')


def _site_gates(pages_html: dict[str, str], brief: DesignBrief, system: DesignSystem) -> list[SiteGateResult]:
    """The deterministic site-level wall. String-and-DOM facts only."""
    results: list[SiteGateResult] = []

    # nav-links-resolve: every page reaches every page.
    missing: list[str] = []
    for slug, html in pages_html.items():
        hrefs = set(_HREF.findall(html))
        for other in brief.pages:
            if other == slug:
                continue
            if f"{other}.html" not in hrefs:
                missing.append(f"{slug}.html has no link to {other}.html")
    results.append(SiteGateResult(
        gate="nav-links-resolve",
        passed=not missing,
        evidence="every page reaches every page" if not missing else "; ".join(missing[:6]),
    ))

    # system-consistency: every page carries the system's skin.
    broken: list[str] = []
    for slug, html in pages_html.items():
        for key, value in system.palette.items():
            if f"--{key}: {value}" not in html:
                broken.append(f"{slug}.html missing --{key}: {value}")
        head_font = system.heading_font.split(",")[0].strip().strip("'\"")
        if head_font and head_font not in html:
            broken.append(f"{slug}.html missing heading font {head_font!r}")
    results.append(SiteGateResult(
        gate="system-consistency",
        passed=not broken,
        evidence="one system, every page" if not broken else "; ".join(broken[:6]),
    ))
    return results


def build_site(
    goal: str,
    provider: ModelProvider,
    memory: MemoryStore,
    search_client: "SearchClient",
    *,
    per_angle: int = 2,
    max_pages: int = 4,
    page_attempts: int = 3,
) -> SiteResult:
    """The agency, end to end. See module docstring for the wall map."""
    # 1 — the brief (one honest retry).
    agent = BriefAgent(provider)
    raw = agent.propose(goal)
    try:
        brief = parse_design_brief(raw, goal)
    except BriefParseError as exc:
        raw = agent.propose(goal, feedback=str(exc))
        try:
            brief = parse_design_brief(raw, goal)
        except BriefParseError as exc2:
            raise SiteBriefRejected(str(exc2)) from exc2
    brief.pages = brief.pages[:max_pages]

    # 2 — the design corpus, in parallel.
    sources = acquire_design_corpus(brief, search_client, per_angle=per_angle)
    corpus_ids = {f"src{i + 1}" for i in range(len(sources))}
    corpus_text = "\n\n".join(
        f"source id: src{i + 1}\n{s.corpus_entry()[:1500]}" for i, s in enumerate(sources)
    ) or "source id: none\n(no design corpus reachable — synthesize from the brief alone, cite nothing)"

    # 3 — the synthesis, with provenance (one honest retry).
    synth = SynthesisAgent(provider)
    raw = synth.propose(brief.brief(), corpus_text)
    try:
        system = parse_design_system(raw, brief, corpus_ids)
    except DesignSystemParseError as exc:
        raw = synth.propose(brief.brief(), corpus_text, feedback=str(exc))
        try:
            system = parse_design_system(raw, brief, corpus_ids)
        except DesignSystemParseError as exc2:
            raise SiteSynthesisRejected(str(exc2)) from exc2

    # 4 — one page build per brief page, through the existing wall.
    pages: dict[str, PageResult] = {}
    for page in brief.pages:
        pages[page] = build_page(
            _page_goal(page, brief, system), provider, memory, max_attempts=page_attempts,
        )

    # 5 — the site gates, plus one repair round for site-level breaks.
    def html_map() -> dict[str, str]:
        return {
            slug: (getattr(getattr(r, "page_outcome", None), "artifact", None).payload
                   if getattr(getattr(r, "page_outcome", None), "artifact", None) else "")
            for slug, r in pages.items()
        }

    gates = _site_gates(html_map(), brief, system)
    if not all(g.passed for g in gates):
        feedback = "; ".join(g.evidence for g in gates if not g.passed)
        for slug in brief.pages:
            mentioned = f"{slug}.html" in feedback
            if mentioned:
                pages[slug] = build_page(
                    _page_goal(slug, brief, system,
                               extra=f"PREVIOUS SITE-LEVEL FAILURE to fix: {feedback}"),
                    provider, memory, max_attempts=page_attempts,
                )
        gates = _site_gates(html_map(), brief, system)

    accepted = all(r.accepted for r in pages.values()) and all(g.passed for g in gates)

    # 6 — the context graph + design knowledge persistence (verified only).
    context_graph = {
        "goal": goal,
        "industry": brief.industry,
        "layout": system.layout,
        "pages": {p: system.components_by_page[p] for p in brief.pages},
        "influences": [
            {"source": inf.source, "pattern": inf.pattern} for inf in system.inspired_by
        ],
        "palette": system.palette,
    }
    if accepted:
        existing = {r.title for r in memory.load_all() if r.category == "entity"}
        def persist(title: str, body: dict, tags: list[str]) -> None:
            if title in existing:
                return
            memory.persist(MemoryRecord(
                category="entity", title=title, body=json.dumps(body),
                tags=["design-kg", *tags], provenance={"goal": goal},
            ))
        persist(f"layout:{system.layout}", {"layout": system.layout, "industry": brief.industry},
                ["layout", brief.industry])
        for inf in system.inspired_by:
            if inf.pattern:
                persist(f"pattern:{inf.pattern[:60]}",
                        {"pattern": inf.pattern, "industry": brief.industry}, ["pattern"])

    return SiteResult(
        goal=goal, brief=brief, system=system, sources=list(sources),
        pages=pages, site_gates=gates, accepted=accepted, context_graph=context_graph,
    )
