"""The Design Intelligence contracts: brief, corpus, synthesis-with-provenance.

Pinned: page and component vocabularies are closed; palettes must be real
hex; the landing page leads; and — the load-bearing one — an influence
that can't name a corpus source is refused. Synthesis over copying is a
parse rule here, not a slogan.
"""

import pytest

from commons.parallel_client import ExtractResult, ScriptedSearchClient, SearchResult
from orgs.web_studio.design_intelligence import (
    DESIGN_ANGLES,
    BriefParseError,
    DesignSystemParseError,
    acquire_design_corpus,
    parse_design_brief,
    parse_design_system,
)


BRIEF = (
    '{"industry": "healthcare AI", "audience": ["doctors", "investors"],'
    ' "brand_qualities": ["trustworthy", "scientific"],'
    ' "user_goals": ["lead generation", "credibility"],'
    ' "pages": ["about", "landing", "pricing"],'
    ' "design_intents": ["medical trust", "enterprise credibility"]}'
)


def test_brief_parses_and_landing_leads():
    brief = parse_design_brief(BRIEF, goal="site for an AI healthcare startup")
    assert brief.pages[0] == "landing", "the front door leads, whatever order proposed"
    assert brief.pages == ["landing", "about", "pricing"]
    assert "medical trust" in brief.brief()


def test_brief_refuses_unknown_pages():
    with pytest.raises(BriefParseError, match="unknown page type"):
        parse_design_brief(
            '{"pages": ["landing", "metaverse_lobby"], "design_intents": ["x"]}', goal="g"
        )


def _system_json(source="src1"):
    return (
        '{"layout": "enterprise_saas",'
        ' "palette": {"bg": "#0B0E14", "surface": "#151A23", "ink": "#E8ECF3", "accent": "#4A90D9"},'
        ' "heading_font": "Inter, system-ui, sans-serif",'
        ' "body_font": "Inter, system-ui, sans-serif",'
        ' "components_by_page": {"landing": ["hero", "features", "cta"],'
        ' "about": ["team"], "pricing": ["pricing_table"]},'
        f' "inspired_by": [{{"source": "{source}", "pattern": "restrained hero, strong proof row"}}],'
        ' "rationale": "clinical credibility over flash"}'
    )


def test_design_system_parses_and_frames_every_page():
    brief = parse_design_brief(BRIEF, goal="g")
    system = parse_design_system(_system_json(), brief, corpus_ids={"src1", "src2"})
    assert system.layout == "enterprise_saas"
    assert system.palette["bg"] == "#0b0e14", "hex normalized lowercase"
    for comps in system.components_by_page.values():
        assert "nav" in comps and "footer" in comps, "every page carries the frame"
    assert ":root {" in system.css_variables() and "--accent: #4a90d9;" in system.css_variables()


def test_influence_without_a_corpus_source_is_refused():
    brief = parse_design_brief(BRIEF, goal="g")
    with pytest.raises(DesignSystemParseError, match="can't name its source"):
        parse_design_system(_system_json(source="vibes"), brief, corpus_ids={"src1"})


def test_bad_hex_and_unknown_component_refused():
    brief = parse_design_brief(BRIEF, goal="g")
    bad_hex = _system_json().replace("#0B0E14", "midnight blue")
    with pytest.raises(DesignSystemParseError, match="hex"):
        parse_design_system(bad_hex, brief, corpus_ids={"src1"})
    bad_comp = _system_json().replace('"hero"', '"hologram_carousel"')
    with pytest.raises(DesignSystemParseError, match="unknown component"):
        parse_design_system(bad_comp, brief, corpus_ids={"src1"})


def test_design_corpus_rides_the_shared_fan_out():
    brief = parse_design_brief(BRIEF, goal="g")
    intent = "; ".join(brief.design_intents[:3])
    client = ScriptedSearchClient(
        search_by_query={
            f"{DESIGN_ANGLES['award_winners'][0]} — {intent}": [
                SearchResult(url="https://awards.example/site", title="Winner"),
            ],
            f"{DESIGN_ANGLES['competitors'][0]} healthcare AI": [
                SearchResult(url="https://rival.example", title="Rival"),
            ],
        },
        extract_by_url={
            "https://awards.example/site": ExtractResult(
                url="https://awards.example/site", title="Winner", content="clean hero"),
            "https://rival.example": ExtractResult(
                url="https://rival.example", title="Rival", content="stock photos everywhere"),
        },
    )
    sources = acquire_design_corpus(
        brief, client, angles=["award_winners", "competitors", "conversion"]
    )
    assert {s.angle for s in sources} == {"award_winners", "competitors"}, (
        "the empty conversion angle returns nothing, honestly"
    )
