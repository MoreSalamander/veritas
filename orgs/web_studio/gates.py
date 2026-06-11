"""P14a — the Web Studio gates: HARD checks over a rendered page.

Every gate here decides on a RenderResult — the structural truth of the page after a real
browser rendered it. None of them ask whether the UI is *good-looking*; that's judgment and
stays out of the hard floor (a soft aesthetic gate comes later). They ask whether it is
structurally correct: it rendered cleanly, the required elements exist, nothing overflows,
and the basics of accessibility hold. These are the front-end equivalent of the software
org's syntax/properties/security gates — the floor a UI must clear before anyone argues taste.
"""

from __future__ import annotations

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from orgs.web_studio.browser import RenderResult


class _RenderGateBase(Gate):
    """All Web Studio gates rule on a RenderResult produced once by the pipeline, so a single
    browser render feeds the whole gate chain."""

    determinism = Determinism.HARD

    def __init__(self, render: RenderResult) -> None:
        self.render = render


class RenderGate(_RenderGateBase):
    """The page must actually load and run with no errors. A console error or an uncaught
    exception means the UI is broken on arrival, whatever it looks like."""

    name = "render"

    def check(self, artifact: Artifact) -> GateResult:
        if not self.render.ok:
            return self._result(False, f"page failed to render: {self.render.error}")
        if self.render.console_errors:
            first = self.render.console_errors[0]
            n = len(self.render.console_errors)
            return self._result(False, f"{n} console error(s); first: {first}")
        return self._result(True, "rendered with no console errors")


class LayoutGate(_RenderGateBase):
    """No horizontal overflow — the page fits its viewport. This is the front-end
    metamorphic check: scrollWidth must not exceed clientWidth, regardless of content. It is
    exactly the bug class that needs a real layout engine to catch."""

    name = "layout"

    def check(self, artifact: Artifact) -> GateResult:
        if self.render.overflow:
            return self._result(
                False,
                f"horizontal overflow: scrollWidth {self.render.scroll_width} > "
                f"clientWidth {self.render.client_width}",
            )
        return self._result(True, f"fits the viewport ({self.render.client_width}px, no overflow)")


class StructureGate(_RenderGateBase):
    """The required elements must be present in the rendered DOM. The selectors are the
    UI's oracle-free contract — "this page must contain a nav, an h1, and a #run button" —
    checked against the real DOM, never against a model's claim that it's there."""

    name = "structure"

    def __init__(self, render: RenderResult, required: list[str]) -> None:
        super().__init__(render)
        self.required = required

    def check(self, artifact: Artifact) -> GateResult:
        if not self.required:
            return self._result(True, "no required elements declared")
        missing = [sel for sel in self.required if not self.render.selectors_present.get(sel)]
        if missing:
            return self._result(False, f"missing required element(s): {', '.join(missing)}")
        return self._result(True, f"all {len(self.required)} required element(s) present")


class A11yGate(_RenderGateBase):
    """The accessibility floor: every image has alt text, every button has an accessible
    label, and the page has exactly one h1. Deterministic, no judgment — a screen reader
    either has what it needs or it doesn't."""

    name = "a11y"

    def check(self, artifact: Artifact) -> GateResult:
        problems: list[str] = []
        if self.render.images_without_alt:
            problems.append(f"{self.render.images_without_alt} image(s) without alt text")
        if self.render.buttons_without_label:
            problems.append(f"{self.render.buttons_without_label} button(s) without a label")
        if self.render.h1_count == 0:
            problems.append("no h1 (page has no main heading)")
        elif self.render.h1_count > 1:
            problems.append(f"{self.render.h1_count} h1 elements (should be exactly one)")
        if problems:
            return self._result(False, "; ".join(problems))
        return self._result(True, "alt text, button labels, and a single h1 all present")
