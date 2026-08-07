"""The site build: the design agency end to end, offline provider, REAL browser.

Pinned: the flow runs brief -> corpus -> synthesis -> per-page wall -> site
gates; the site gates are deterministic string-and-DOM facts (every page
reaches every page; one design system on every page); a page that drops the
palette fails the SITE even when it passes its own wall; verified design
knowledge persists as design-kg entities.
"""

import json

from commons.parallel_client import ExtractResult, ScriptedSearchClient, SearchResult
from engine.memory import MemoryStore
from engine.model import SequencedProvider
from orgs.web_studio.design_intelligence import DESIGN_ANGLES
from orgs.web_studio.site import build_site

BRIEF = json.dumps({
    "industry": "healthcare AI",
    "audience": ["doctors"],
    "brand_qualities": ["trust"],
    "user_goals": ["credibility"],
    "pages": ["landing", "pricing"],
    "design_intents": ["medical trust"],
})

SYSTEM = json.dumps({
    "layout": "enterprise_saas",
    "palette": {"bg": "#0b0e14", "surface": "#151a23", "ink": "#e8ecf3", "accent": "#4a90d9"},
    "heading_font": "Georgia, serif",
    "body_font": "Georgia, serif",
    "components_by_page": {"landing": ["hero", "cta"], "pricing": ["pricing_table"]},
    "inspired_by": [{"source": "src1", "pattern": "restrained hero"}],
    "rationale": "clinical calm",
})

VARS = ":root { --accent: #4a90d9; --bg: #0b0e14; --ink: #e8ecf3; --surface: #151a23; }"


def _page(slug: str, other: str, *, with_vars: bool = True) -> str:
    style = f"<style>{VARS if with_vars else ''} h1 {{ font-family: Georgia, serif; }}</style>"
    return (
        f"<!doctype html><html lang='en'><head><title>{slug}</title>{style}</head><body>"
        f"<nav><a href=\"{slug}.html\">{slug}</a> <a href=\"{other}.html\">{other}</a></nav>"
        f"<header class=\"hero\"><h1>Georgia headline for {slug}</h1></header>"
        f"<section class=\"pricing cta\"><button>Choose</button></section>"
        f"<footer>fin</footer></body></html>"
    )


def _spec(slug: str) -> str:
    return json.dumps({
        "title": slug, "description": f"the {slug} page",
        "required_elements": ["nav", "footer"],
    })


def _search():
    intent = "medical trust"
    return ScriptedSearchClient(
        search_by_query={
            f"{DESIGN_ANGLES['award_winners'][0]} — {intent}": [
                SearchResult(url="https://awards.example/x", title="Winner"),
            ],
        },
        extract_by_url={
            "https://awards.example/x": ExtractResult(
                url="https://awards.example/x", title="Winner", content="calm hero, high contrast"),
        },
    )


def test_site_builds_and_site_gates_hold(tmp_path):
    provider = SequencedProvider({
        "designer": [BRIEF, SYSTEM, _spec("landing"), _spec("pricing")],
        "web-developer": [_page("landing", "pricing"), _page("pricing", "landing")],
    })
    memory = MemoryStore(tmp_path / "mem")
    site = build_site("a site for an AI healthcare startup", provider, memory, _search())

    assert site.accepted
    assert site.brief.pages == ["landing", "pricing"]
    assert [g.gate for g in site.site_gates] == ["nav-links-resolve", "system-consistency"]
    assert all(g.passed for g in site.site_gates)
    assert "Georgia" in site.page_html("landing")
    assert site.context_graph["layout"] == "enterprise_saas"
    assert site.context_graph["influences"][0]["source"] == "src1"

    titles = {r.title for r in memory.load_all() if r.category == "entity"}
    assert "layout:enterprise_saas" in titles
    assert any(t.startswith("pattern:restrained hero") for t in titles)


def test_dropping_the_palette_fails_the_site_not_just_the_page(tmp_path):
    # pricing forgets the design system; its own wall passes, the SITE gate
    # refuses — and the repair round rebuilds it with the failure named.
    provider = SequencedProvider({
        "designer": [BRIEF, SYSTEM, _spec("landing"), _spec("pricing"), _spec("pricing")],
        "web-developer": [
            _page("landing", "pricing"),
            _page("pricing", "landing", with_vars=False),   # first try: no palette
            _page("pricing", "landing"),                    # repair: carries it
        ],
    })
    memory = MemoryStore(tmp_path / "mem")
    site = build_site("a site for an AI healthcare startup", provider, memory, _search())
    consistency = next(g for g in site.site_gates if g.gate == "system-consistency")
    assert consistency.passed, "the repair round must fix the skinless page"
    assert site.accepted
