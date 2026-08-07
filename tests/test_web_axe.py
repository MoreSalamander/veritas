"""AccessGuard folded into the page wall: axe-core as a HARD gate.

Real browser, real axe engine — the same vendored bundle the standalone
scanner runs. Pinned: a critical violation (image without alt) fails the
page with the rule named; a clean page passes with the AccessGuard score
credited; a missing engine fails CLOSED, never silently passes.
"""

from orgs.web_studio.browser import BrowserExecutor, RenderResult
from orgs.web_studio.gates import AxeGate

CLEAN = (
    "<!doctype html><html lang='en'><head><title>Clean</title></head><body>"
    "<nav><a href='#m'>Home</a></nav><main id='m'><h1>Fine page</h1>"
    "<img src='data:image/gif;base64,R0lGODlhAQABAAAAACw=' alt='a dot'>"
    "<button>Go</button></main><footer>fin</footer></body></html>"
)

# image-alt is a CRITICAL rule — the same violation AccessGuard's own W3C
# bad-demo scan recorded (impact: critical, rule: image-alt).
NO_ALT = CLEAN.replace(" alt='a dot'", "")


def test_critical_violation_fails_the_wall():
    render = BrowserExecutor().render(NO_ALT)
    result = AxeGate(render).check(artifact=None)
    assert not result.passed
    assert "image-alt" in result.evidence and "critical" in result.evidence
    assert "AccessGuard score" in result.evidence


def test_clean_page_passes_with_score():
    render = BrowserExecutor().render(CLEAN)
    result = AxeGate(render).check(artifact=None)
    assert result.passed, result.evidence
    assert "AccessGuard score" in result.evidence


def test_missing_engine_fails_closed():
    render = RenderResult(ok=True, axe_error="axe engine missing at /nowhere")
    result = AxeGate(render).check(artifact=None)
    assert not result.passed
    assert "unverified" in result.evidence
