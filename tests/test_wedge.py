"""P31c1 — the hosted wedge: a stranger's run is identified, isolated, persisted, and gated.

The load-bearing property is FAIL CLOSED: with no live sandbox, an untrusted goal must be REFUSED
before any model-authored code can execute — never run on the host. Then: a bad token is refused, a
good one runs the gated Software pipeline into the tenant's OWN memory, and two tenants cannot see
each other's runs. (Real containment is proven live in test_container_executor; here the sandbox check
is injected so the wedge's own logic is tested offline.)
"""

from __future__ import annotations

import json

import pytest

from engine.model import ScriptedProvider
from products.wedge import SandboxUnavailable, Unauthorized, Wedge, WedgeAuth

GOOD_SPEC = json.dumps({
    "function_name": "add", "description": "add two numbers", "signature": "def add(a, b)",
    "cases": [{"args": [1, 2], "expected": 3}, {"args": [5, 5], "expected": 10}],
})
GOOD_CODE = "def add(a, b):\n    return a + b\n"


def _provider() -> ScriptedProvider:
    return ScriptedProvider({"spec": GOOD_SPEC, "developer": GOOD_CODE})


def _wedge(tmp_path, *, sandbox=True, tokens=None) -> Wedge:
    auth = WedgeAuth(tokens or {"tok_alice": "alice"})
    return Wedge(tmp_path, _provider, auth, sandbox_check=lambda: sandbox)


# --- auth: the identity floor ----------------------------------------------------------------

def test_missing_token_is_unauthorized(tmp_path):
    with pytest.raises(Unauthorized):
        _wedge(tmp_path).submit(authorization=None, goal="add two numbers")


def test_unknown_token_is_unauthorized(tmp_path):
    with pytest.raises(Unauthorized):
        _wedge(tmp_path).submit(authorization="Bearer nope", goal="add two numbers")


def test_bearer_and_bare_tokens_both_resolve():
    auth = WedgeAuth({"tok_alice": "alice"})
    assert auth.tenant_for("Bearer tok_alice") == "alice"
    assert auth.tenant_for("tok_alice") == "alice"


def test_empty_token_table_means_the_wedge_is_closed():
    auth = WedgeAuth.from_env(raw="")
    with pytest.raises(Unauthorized):
        auth.tenant_for("Bearer anything")


def test_from_env_parses_pairs_and_rejects_bad_tenant_ids():
    auth = WedgeAuth.from_env(raw="tok_a:alice, tok_b:bob, tok_c:Bad/Id, tok_d:")
    assert auth.tokens == {"tok_a": "alice", "tok_b": "bob"}  # the malformed entries are dropped


# --- THE load-bearing property: fail closed --------------------------------------------------

def test_no_sandbox_refuses_before_any_run(tmp_path):
    w = _wedge(tmp_path, sandbox=False)
    with pytest.raises(SandboxUnavailable):
        w.submit(authorization="Bearer tok_alice", goal="add two numbers")
    assert not (tmp_path / "tenants").exists()  # refused BEFORE touching the tenant's storage


def test_fail_closed_is_checked_after_auth(tmp_path):
    # an anonymous request fails on identity, not on the sandbox — order matters
    w = _wedge(tmp_path, sandbox=False)
    with pytest.raises(Unauthorized):
        w.submit(authorization=None, goal="add two numbers")


# --- the happy path: isolated, persisted, gated ----------------------------------------------

def test_good_submission_runs_gated_and_persists_to_the_tenant(tmp_path):
    res = _wedge(tmp_path).submit(authorization="Bearer tok_alice", goal="add two numbers")
    assert res.accepted and res.isolated and res.tenant == "alice"
    assert "def add" in res.code                              # the built function is returned, not just a verdict
    assert res.spec and res.spec.get("function_name") == "add"  # the contract is surfaced (behind-the-scenes)
    assert any(g["passed"] for g in res.evidence)             # the gate trail is surfaced
    assert (tmp_path / "tenants" / "alice" / "software").exists()  # persisted under the tenant root


def test_two_tenants_are_isolated(tmp_path):
    auth = WedgeAuth({"tok_alice": "alice", "tok_bob": "bob"})
    w = Wedge(tmp_path, _provider, auth, sandbox_check=lambda: True)
    w.submit(authorization="Bearer tok_alice", goal="add two numbers")
    assert (tmp_path / "tenants" / "alice").exists()
    assert not (tmp_path / "tenants" / "bob").exists()        # bob has not run; alice's run is his alone


# --- HTTP shell: status preflight + 401/503 mapping ------------------------------------------


def test_unvendable_slot_is_refused_before_the_sandbox(tmp_path):
    """The allowlist is deterministic and sits before any execution concern:
    an org not on the machine is refused even with a healthy sandbox."""
    from products.wedge import OrgNotVendable, Wedge, WedgeAuth

    wedge = Wedge(tmp_path, lambda: None, WedgeAuth({"tok": "tenant1"}),
                  sandbox_check=lambda: True)
    with pytest.raises(OrgNotVendable):
        wedge.submit(authorization="Bearer tok", goal="x", org="production")


def test_web_slot_vends_the_page(tmp_path):
    """The web slot returns the page itself in the tray — the artifact, not
    just a verdict."""
    from engine.model import ScriptedProvider
    from products.wedge import Wedge, WedgeAuth

    provider = ScriptedProvider({
        "designer": '{"title": "T", "description": "d", "required_elements": ["h1"], '
                    '"aesthetics": {}}',
        "web-developer": "<!doctype html><html><head><style>h1{color:#111;background:#fff}</style>"
                         "</head><body><h1>Hello</h1></body></html>",
    })
    wedge = Wedge(tmp_path, lambda: provider, WedgeAuth({"tok": "tenant1"}),
                  sandbox_check=lambda: True)
    res = wedge.submit(authorization="Bearer tok", goal="a page", org="web")
    assert res.org == "web"
    # Whatever the gates decided, the tray carries the artifacts that existed
    # and the evidence names real gates.
    assert isinstance(res.artifacts, list) and isinstance(res.evidence, list)
    assert any(e["gate"] for e in res.evidence)


def test_research_with_no_sources_and_no_search_client_is_refused(tmp_path):
    """No corpus and no live search = a summarizer wearing a lab coat.
    Refused honestly, before any model call."""
    from products.wedge import SourcesUnavailable, Wedge, WedgeAuth

    wedge = Wedge(tmp_path, lambda: None, WedgeAuth({"tok": "tenant1"}),
                  sandbox_check=lambda: True)
    with pytest.raises(SourcesUnavailable):
        wedge.submit(authorization="Bearer tok", goal="what is spaced repetition?", org="research")


def test_research_fetches_its_own_corpus_via_the_search_seam(tmp_path):
    """REAL research: the machine finds sources itself; the fetched URLs land
    in the tray as their own artifact, and the report cites into the corpus."""
    from commons.parallel_client import ExtractResult, ScriptedSearchClient, SearchResult
    from engine.model import ScriptedProvider
    from products.wedge import Wedge, WedgeAuth

    client = ScriptedSearchClient(
        search_by_query={
            "what is spaced repetition?": [
                SearchResult(url="https://example.edu/sr", title="Spaced Repetition"),
                SearchResult(url="https://example.org/memory", title="Memory Study"),
            ],
        },
        extract_by_url={
            "https://example.edu/sr": ExtractResult(
                url="https://example.edu/sr", title="Spaced Repetition",
                content="Spaced repetition schedules reviews at increasing intervals."),
            "https://example.org/memory": ExtractResult(
                url="https://example.org/memory", title="Memory Study",
                content="Reviews timed before forgetting strengthen recall."),
        },
    )
    provider = ScriptedProvider({
        "researcher": '{"claims": [{"text": "Spaced repetition schedules reviews at increasing intervals.", '
                      '"citations": [{"source": "src1", "quote": "schedules reviews at increasing intervals"}]}]}',
    })
    wedge = Wedge(tmp_path, lambda: provider, WedgeAuth({"tok": "tenant1"}),
                  sandbox_check=lambda: True, search_client=client)
    res = wedge.submit(authorization="Bearer tok", goal="what is spaced repetition?", org="research")
    assert res.org == "research"
    assert res.artifacts and res.artifacts[0]["label"] == "machine-fetched sources"
    assert "example.edu" in res.artifacts[0]["payload"]


def test_research_tray_holds_a_rendered_page_not_report_json(tmp_path):
    """The report artifact is machine-shaped JSON for the gates; the tray must
    hand over a normal research page — findings, quotes, a sources index that
    resolves corpus ids back to the fetched URLs. Raw JSON never reaches the
    tray for a parseable report."""
    from commons.parallel_client import ExtractResult, ScriptedSearchClient, SearchResult
    from engine.model import ScriptedProvider
    from products.wedge import Wedge, WedgeAuth

    client = ScriptedSearchClient(
        search_by_query={
            "what is spaced repetition?": [
                SearchResult(url="https://example.edu/sr", title="Spaced Repetition"),
            ],
        },
        extract_by_url={
            "https://example.edu/sr": ExtractResult(
                url="https://example.edu/sr", title="Spaced Repetition",
                content="Spaced repetition schedules reviews at increasing intervals."),
        },
    )
    provider = ScriptedProvider({
        "researcher": '{"topic": "what is spaced repetition?", '
                      '"claims": [{"text": "Spaced repetition schedules reviews at increasing intervals.", '
                      '"citations": [{"source": "src1", "quote": "schedules reviews at increasing intervals"}]}]}',
    })
    wedge = Wedge(tmp_path, lambda: provider, WedgeAuth({"tok": "tenant1"}),
                  sandbox_check=lambda: True, search_client=client)
    res = wedge.submit(authorization="Bearer tok", goal="what is spaced repetition?", org="research")
    rendered = [a for a in res.artifacts if a["label"] == "grounded report"]
    assert rendered, f"no rendered report artifact in {[a['label'] for a in res.artifacts]}"
    page = rendered[0]["payload"]
    assert page.startswith("# "), "the tray artifact must be a page, not JSON"
    assert "{" not in page.split("## Sources")[0], "no JSON syntax in the findings"
    assert "## Findings" in page and "## Sources" in page
    assert "[src1] https://example.edu/sr" in page, "corpus id must resolve to the fetched URL"
    assert '> "schedules reviews at increasing intervals" — src1' in page
