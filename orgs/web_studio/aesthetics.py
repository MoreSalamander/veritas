"""P19 — measurable-aesthetic gates: the part of 'taste' that is a fact.

A surprising amount of "does this match my aesthetic" is computable from the rendered page:
the background is dark or it isn't, the text clears a contrast ratio or it doesn't, the fonts
and colors are on the approved list or they aren't. Those are facts, so they can be HARD gates —
the deterministic floor under create mode. What's left ("is it elegant?") stays soft/human in
later phases. No LLM, no judgment here: explicit criteria, checked against a real render.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from orgs.web_studio.browser import RenderResult


def normalize_color(c: str) -> str:
    """Normalize a hex or rgb()/rgba() color to a canonical 'rgb(r,g,b)' string."""
    c = c.strip().lower()
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) >= 6:
            return f"rgb({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)})"
        return c
    nums = re.findall(r"-?\d+\.?\d*", c)
    if c.startswith("rgb") and len(nums) >= 3:
        return f"rgb({int(float(nums[0]))},{int(float(nums[1]))},{int(float(nums[2]))})"
    return c


@dataclass
class AestheticCriteria:
    """Explicit, checkable design intent — the part of an aesthetic that is measurable."""

    theme: str | None = None            # "dark" | "light"
    min_contrast: float | None = None   # WCAG ratio, e.g. 4.5
    fonts: list[str] | None = None      # allowed font-family names
    palette: list[str] | None = None    # allowed colors (hex or rgb)


class ThemeGate(Gate):
    """HARD: the page is dark/light as required (background luminance below/above 0.5)."""

    name = "theme"
    determinism = Determinism.HARD

    def __init__(self, render: RenderResult, theme: str) -> None:
        self.render = render
        self.theme = theme.lower()

    def check(self, artifact: Artifact) -> GateResult:
        lum = self.render.background_luminance
        is_dark = lum < 0.5
        ok = is_dark == (self.theme == "dark")
        seen = "dark" if is_dark else "light"
        return self._result(ok, f"background is {seen} (luminance {lum:.2f}); wanted {self.theme}")


class ContrastGate(Gate):
    """HARD: the worst text-vs-background contrast clears the required WCAG ratio."""

    name = "contrast"
    determinism = Determinism.HARD

    def __init__(self, render: RenderResult, min_contrast: float) -> None:
        self.render = render
        self.min_contrast = min_contrast

    def check(self, artifact: Artifact) -> GateResult:
        ok = self.render.min_contrast >= self.min_contrast
        return self._result(
            ok, f"min text contrast {self.render.min_contrast:.1f}:1 (need ≥ {self.min_contrast})"
        )


class FontGate(Gate):
    """HARD: only approved font families are used."""

    name = "fonts"
    determinism = Determinism.HARD

    def __init__(self, render: RenderResult, allowed: list[str]) -> None:
        self.render = render
        self.allowed = {f.strip().lower() for f in allowed}

    def check(self, artifact: Artifact) -> GateResult:
        extra = sorted({f for f in self.render.fonts if f and f not in self.allowed})
        if extra:
            return self._result(False, f"off-spec font(s): {', '.join(extra)}")
        return self._result(True, f"only approved fonts used ({', '.join(sorted(self.allowed))})")


class PaletteGate(Gate):
    """HARD: only approved colors appear in the render."""

    name = "palette"
    determinism = Determinism.HARD

    def __init__(self, render: RenderResult, palette: list[str]) -> None:
        self.render = render
        self.palette = {normalize_color(c) for c in palette}

    def check(self, artifact: Artifact) -> GateResult:
        off = sorted({normalize_color(c) for c in self.render.colors} - self.palette)
        if off:
            return self._result(False, f"off-palette color(s): {', '.join(off)}")
        return self._result(True, f"all colors within the {len(self.palette)}-color palette")


def aesthetic_gates(render: RenderResult, criteria: AestheticCriteria) -> list[Gate]:
    """Build the gate list for whichever criteria were declared — only check what's asked."""
    gates: list[Gate] = []
    if criteria.theme is not None:
        gates.append(ThemeGate(render, criteria.theme))
    if criteria.min_contrast is not None:
        gates.append(ContrastGate(render, criteria.min_contrast))
    if criteria.fonts is not None:
        gates.append(FontGate(render, criteria.fonts))
    if criteria.palette is not None:
        gates.append(PaletteGate(render, criteria.palette))
    return gates
