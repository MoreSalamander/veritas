"""The Research Intelligence layer: plan contract + parallel acquisition.

Pinned: the plan parser refuses angles outside the closed vocabulary and
plans with nothing to ask; acquisition fans out per angle, tags every
source with the angle that found it, de-dupes by URL across angles, and
survives a dead angle without sinking the haul.
"""

import pytest

from commons.parallel_client import ExtractResult, ScriptedSearchClient, SearchResult
from orgs.research_studio.intelligence import (
    ANGLES,
    PlanParseError,
    acquire_parallel,
    parse_plan,
)


def test_plan_parses_and_caps():
    plan = parse_plan(
        '{"domain": "hardware", "questions": ["q1", "q2"],'
        ' "angles": ["academic", "news", "academic"], "unknowns": ["u1"]}',
        topic="the future of AI hardware",
    )
    assert plan.domain == "hardware"
    assert plan.angles == ["academic", "news"], "de-duped, order kept"
    assert "RESEARCH PLAN" in plan.brief() and "Peer-reviewed" in plan.brief()


def test_plan_refuses_unknown_angles_and_empty_questions():
    with pytest.raises(PlanParseError, match="unknown angle"):
        parse_plan('{"questions": ["q"], "angles": ["vibes"]}', topic="t")
    with pytest.raises(PlanParseError, match="no research questions"):
        parse_plan('{"questions": [], "angles": ["news"]}', topic="t")


def _client():
    return ScriptedSearchClient(
        search_by_query={
            f"t {ANGLES['academic'][0]}": [
                SearchResult(url="https://arxiv.example/1", title="Paper"),
                SearchResult(url="https://shared.example/x", title="Shared"),
            ],
            f"t {ANGLES['news'][0]}": [
                SearchResult(url="https://news.example/2", title="Story"),
                SearchResult(url="https://shared.example/x", title="Shared"),
            ],
        },
        extract_by_url={
            "https://arxiv.example/1": ExtractResult(
                url="https://arxiv.example/1", title="Paper", content="paper text"),
            "https://news.example/2": ExtractResult(
                url="https://news.example/2", title="Story", content="news text"),
            "https://shared.example/x": ExtractResult(
                url="https://shared.example/x", title="Shared", content="shared text"),
        },
    )


def test_acquisition_tags_angles_and_dedupes_across_them():
    plan = parse_plan(
        '{"questions": ["q"], "angles": ["academic", "news"]}', topic="t"
    )
    sources = acquire_parallel(plan, _client(), per_angle=2)
    by_url = {s.url: s for s in sources}
    assert set(by_url) == {
        "https://arxiv.example/1", "https://news.example/2", "https://shared.example/x",
    }
    assert by_url["https://arxiv.example/1"].angle == "academic"
    assert by_url["https://news.example/2"].angle == "news"
    assert "ANGLE: academic" in by_url["https://arxiv.example/1"].corpus_entry()


def test_a_dead_angle_never_sinks_the_haul():
    plan = parse_plan(
        '{"questions": ["q"], "angles": ["academic", "patents"]}', topic="t"
    )
    # The scripted client knows nothing about the patents query -> that
    # worker raises inside search and must return nothing, honestly.
    sources = acquire_parallel(plan, _client(), per_angle=2)
    assert {s.angle for s in sources} == {"academic"}
    assert len(sources) == 2


def test_build_intelligence_end_to_end(tmp_path):
    """The whole flow, offline: plan -> parallel angles -> grounded v2
    report -> context graph -> entities persisted -> next run briefed."""
    import json

    from engine.memory import MemoryStore
    from engine.model import ScriptedProvider, SequencedProvider
    from orgs.research_studio.pipeline import build_intelligence

    plan_json = json.dumps({
        "domain": "test domain",
        "questions": ["what is t?"],
        "angles": ["academic", "news"],
        "unknowns": ["u"],
    })
    report_json = json.dumps({
        "topic": "t",
        "claims": [{
            "text": "Papers exist about t.",
            "citations": [{"source": "src1", "quote": "paper text"}],
        }],
        "entities": [
            {"name": "T-Tech", "type": "technology", "description": "the thing"},
            {"name": "T-Corp", "type": "company", "description": "who builds it"},
        ],
        "relationships": [
            {"source": "T-Corp", "relation": "improves", "target": "T-Tech", "claim_index": 0},
        ],
        "open_questions": ["when does T-Tech ship?"],
    })

    class Provider(SequencedProvider):
        pass

    provider = SequencedProvider({
        "researcher": [plan_json, report_json],
        "judge": ['{"unsupported": []}'],
    })
    memory = MemoryStore(tmp_path / "mem")
    res = build_intelligence("t", provider, memory, _client(), per_angle=2)

    assert res.accepted
    assert res.plan.angles == ["academic", "news"]
    assert {s.angle for s in res.sources} == {"academic", "news"}
    assert [e["name"] for e in res.context_graph["entities"]] == ["T-Tech", "T-Corp"]
    assert res.context_graph["relationships"][0]["relation"] == "improves"
    assert res.context_graph["open_questions"] == ["when does T-Tech ship?"]

    # The knowledge layer remembers — entities persisted, verified runs only.
    cats = [(r.category, r.title) for r in memory.load_all()]
    assert ("entity", "T-Tech") in cats and ("entity", "T-Corp") in cats
    assert any(c == "relationship" for c, _ in cats)

    # The next run starts briefed: the planner's prompt carries known entities.
    seen_prompts = []

    class Spy(ScriptedProvider):
        def propose(self, *, role, prompt, system=None):
            seen_prompts.append(prompt)
            return super().propose(role=role, prompt=prompt, system=system)

    spy = Spy({"researcher": plan_json, "judge": '{"unsupported": []}'})
    try:
        build_intelligence("T-Tech roadmap", spy, memory, _client(), per_angle=2)
    except Exception:
        pass  # acquisition for the new topic finds nothing scripted; the briefing already happened
    assert any("KNOWN ENTITIES" in p and "T-Tech" in p for p in seen_prompts)
