"""P14a — the Web Studio spine: a real browser renders a page and HARD gates decide.

No LLM, no judgment — every check here is a structural fact of the rendered DOM. A good page
clears the floor; each mutant trips exactly the gate that owns its defect. This is the
front-end equivalent of test_spine + test_properties: prove the verification model before any
cast exists.
"""

from __future__ import annotations

from engine.artifact import Artifact
from orgs.web_studio.browser import BrowserExecutor, RenderResult
from orgs.web_studio.gates import A11yGate, LayoutGate, RenderGate, StructureGate

EXEC = BrowserExecutor()

# a valid 1x1 transparent gif, so the good page loads with no network error
_IMG = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="

GOOD = (
    "<!doctype html><html><head><title>Hi</title></head><body>"
    "<nav><a href='#'>Home</a></nav>"
    "<h1>Welcome</h1>"
    f"<img src='{_IMG}' alt='logo'>"
    "<button>Go</button>"
    "</body></html>"
)


def _art() -> Artifact:
    return Artifact.propose(type="page", owner="test", payload="", rationale="test")


def test_good_page_clears_the_whole_floor():
    rr = EXEC.render(GOOD, selectors=["nav", "h1", "button"])
    a = _art()
    assert RenderGate(rr).check(a).passed
    assert LayoutGate(rr).check(a).passed
    assert StructureGate(rr, ["nav", "h1", "button"]).check(a).passed
    assert A11yGate(rr).check(a).passed


def test_console_error_fails_render_gate():
    bad = GOOD.replace("</body>", "<script>throw new Error('boom')</script></body>")
    res = RenderGate(EXEC.render(bad)).check(_art())
    assert not res.passed and "error" in res.evidence


def test_overflow_fails_layout_gate():
    bad = GOOD.replace("</body>", "<div style='width:3000px'>wide</div></body>")
    rr = EXEC.render(bad)
    res = LayoutGate(rr).check(_art())
    assert not res.passed and "overflow" in res.evidence
    assert rr.overflow and rr.scroll_width > rr.client_width


def test_missing_required_element_fails_structure_gate():
    rr = EXEC.render("<!doctype html><html><body><h1>x</h1></body></html>", selectors=["#run"])
    res = StructureGate(rr, ["#run"]).check(_art())
    assert not res.passed and "#run" in res.evidence


def test_image_without_alt_fails_a11y():
    bad = f"<!doctype html><html><body><h1>x</h1><img src='{_IMG}'></body></html>"
    res = A11yGate(EXEC.render(bad)).check(_art())
    assert not res.passed and "alt" in res.evidence


def test_multiple_h1_fails_a11y():
    bad = "<!doctype html><html><body><h1>a</h1><h1>b</h1></body></html>"
    res = A11yGate(EXEC.render(bad)).check(_art())
    assert not res.passed and "h1" in res.evidence


def test_unlabeled_button_fails_a11y():
    bad = "<!doctype html><html><body><h1>x</h1><button></button></body></html>"
    res = A11yGate(EXEC.render(bad)).check(_art())
    assert not res.passed and "button" in res.evidence


def test_render_failure_is_a_verdict_not_a_crash():
    # the ok=False path: a fatal render error becomes a gate verdict, never an exception
    res = RenderGate(RenderResult(ok=False, error="Timeout 15000ms exceeded")).check(_art())
    assert not res.passed and "render" in res.evidence
