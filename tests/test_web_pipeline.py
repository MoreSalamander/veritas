"""P14b — the Web Studio pipeline: goal -> spec -> page, browser-verified, end to end.

Driven offline with a ScriptedProvider (no model), but the page is rendered in a REAL browser
and the gates really decide. A clean page ships; a page missing a required element or
overflowing the viewport is rejected by the gate that owns the defect; a non-executable spec
dies before any HTML is written. Same spine as the software org — proof the engine is general.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.web_studio.pipeline import build_page

SPEC = json.dumps(
    {"title": "Landing", "description": "a simple landing page",
     "required_elements": ["nav", "h1", "button"]}
)
GOOD_PAGE = (
    "<!doctype html><html><head><title>Landing</title></head><body>"
    "<nav><a href='#'>Home</a></nav><h1>Welcome</h1><button>Get started</button>"
    "</body></html>"
)
NO_NAV_PAGE = "<!doctype html><html><body><h1>Welcome</h1><button>go</button></body></html>"
OVERFLOW_PAGE = (
    "<!doctype html><html><body><nav>n</nav><h1>x</h1><button>b</button>"
    "<div style='width:3000px'>wide</div></body></html>"
)


def _provider(spec: str, page: str) -> ScriptedProvider:
    return ScriptedProvider({"designer": spec, "web-developer": page})


def test_clean_page_ships(tmp_path):
    result = build_page("a landing page", _provider(SPEC, GOOD_PAGE), MemoryStore(tmp_path))
    assert result.accepted
    assert result.spec_outcome.accepted
    assert result.page_outcome is not None and result.page_outcome.accepted
    gate_names = [g.gate_name for g in result.page_outcome.artifact.provenance.gate_results]
    assert gate_names == ["render", "layout", "structure", "a11y", "validation"]
    assert result.page_outcome.memory_path.parent.name == "institutional"


def test_missing_required_element_is_rejected(tmp_path):
    result = build_page("a landing page", _provider(SPEC, NO_NAV_PAGE), MemoryStore(tmp_path))
    assert not result.accepted
    assert result.page_outcome is not None and not result.page_outcome.accepted
    structure = next(
        g for g in result.page_outcome.artifact.provenance.gate_results if g.gate_name == "structure"
    )
    assert not structure.passed and "nav" in structure.evidence


def test_overflow_is_rejected(tmp_path):
    result = build_page("a landing page", _provider(SPEC, OVERFLOW_PAGE), MemoryStore(tmp_path))
    assert not result.accepted
    layout = next(
        g for g in result.page_outcome.artifact.provenance.gate_results if g.gate_name == "layout"
    )
    assert not layout.passed and "overflow" in layout.evidence


def test_unusable_spec_dies_before_any_html(tmp_path):
    result = build_page("a landing page", _provider("just make it look nice", GOOD_PAGE),
                        MemoryStore(tmp_path))
    assert not result.accepted
    assert not result.spec_outcome.accepted
    assert result.page_outcome is None  # the developer never ran
    assert result.spec_outcome.memory_path.parent.name == "failures"
