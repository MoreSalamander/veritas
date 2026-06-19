"""P14a — the Web Studio's verification substrate: a real headless browser.

The software org verifies by running Python and checking return values. A UI cannot be
verified that way — "looks right" is judgment, exactly what the scaffold refuses to trust.
But a surprising amount of a UI *is* deterministically checkable, if you actually render it:
it loads without console errors, the required elements are in the DOM, nothing overflows its
container, images have alt text. Those are structural facts about the rendered page, not
opinions — so they can be HARD gates.

This is the new org's Executor seam (sibling to LocalSubprocessExecutor): it renders an HTML
artifact in headless Chromium and reports the structural truth the gates decide on. A real
browser is non-negotiable — the layout facts (overflow) need a real layout engine; a DOM
parser without rendering cannot compute scrollWidth vs clientWidth, and would sail past the
exact class of bug that actually breaks UIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import ConsoleMessage, sync_playwright


@dataclass
class RenderResult:
    """The structural truth of a rendered page. Deterministic given the same HTML."""

    ok: bool
    error: str = ""
    console_errors: list[str] = field(default_factory=list)
    scroll_width: int = 0
    client_width: int = 0
    title: str = ""
    h1_count: int = 0
    images_total: int = 0
    images_without_alt: int = 0
    buttons_without_label: int = 0
    selectors_present: dict[str, bool] = field(default_factory=dict)
    # P19 — measurable aesthetics, read from computed styles after rendering
    background_luminance: float = 1.0  # 0 (black) .. 1 (white); the body's effective bg
    min_contrast: float = 21.0  # worst text-vs-background WCAG ratio (21 = none to check)
    fonts: list[str] = field(default_factory=list)  # distinct font families used (lowercased)
    colors: list[str] = field(default_factory=list)  # distinct text/bg colors used, "rgb(r,g,b)"

    @property
    def overflow(self) -> bool:
        return self.scroll_width > self.client_width


_PROBE = r"""() => {
  const parseRGB = s => { const m = (s||'').match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; };
  const relLum = c => { const f = v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055,2.4); };
    return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b); };
  const ratio = (l1,l2) => { const a=Math.max(l1,l2), b=Math.min(l1,l2); return (a+0.05)/(b+0.05); };
  const effBg = el => { let e=el; while (e) { const c=parseRGB(getComputedStyle(e).backgroundColor);
    if (c && c.a>0) return c; e=e.parentElement; } return {r:255,g:255,b:255,a:1}; };

  const els = [...document.body.querySelectorAll('*')];
  const colors = new Set(), fonts = new Set();
  let minContrast = 21;
  for (const el of els) {
    const cs = getComputedStyle(el);
    const col = parseRGB(cs.color); if (col && col.a>0) colors.add(`rgb(${col.r},${col.g},${col.b})`);
    const bg = parseRGB(cs.backgroundColor); if (bg && bg.a>0) colors.add(`rgb(${bg.r},${bg.g},${bg.b})`);
    fonts.add((cs.fontFamily||'').split(',')[0].replace(/["']/g,'').trim().toLowerCase());
    const hasText = [...el.childNodes].some(n => n.nodeType===3 && n.textContent.trim());
    if (hasText && col && col.a>0) { const c = ratio(relLum(col), relLum(effBg(el))); if (c < minContrast) minContrast = c; }
  }
  return {
    sw: document.documentElement.scrollWidth,
    cw: document.documentElement.clientWidth,
    title: document.title,
    h1: document.querySelectorAll('h1').length,
    imgs: document.images.length,
    imgsNoAlt: [...document.images].filter(i => !i.getAttribute('alt')).length,
    btnsNoLabel: [...document.querySelectorAll('button')].filter(
      b => !(b.textContent || '').trim() && !b.getAttribute('aria-label')).length,
    bgLum: relLum(effBg(document.body)),
    minContrast: minContrast,
    colors: [...colors],
    fonts: [...fonts].filter(Boolean),
  };
}"""


class BrowserExecutor:
    """Renders an HTML artifact in headless Chromium and returns the structural facts the
    gates decide on. One browser launch per render; a fatal load error is captured (never
    raised) so a gate can rule on it rather than the pipeline crashing."""

    def __init__(self, width: int = 1280, height: int = 800) -> None:
        self.width = width
        self.height = height

    def render(
        self, html: str, selectors: list[str] | None = None, timeout: float = 15.0
    ) -> RenderResult:
        selectors = selectors or []
        console_errors: list[str] = []

        def _on_console(msg: ConsoleMessage) -> None:
            if msg.type == "error":
                console_errors.append(msg.text)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": self.width, "height": self.height})
                page.on("console", _on_console)
                page.on("pageerror", lambda exc: console_errors.append(str(exc)))
                page.set_content(html, wait_until="load", timeout=timeout * 1000)
                page.wait_for_timeout(50)  # let any load-time scripts settle
                metrics: dict[str, Any] = page.evaluate(_PROBE)
                present = {sel: page.query_selector(sel) is not None for sel in selectors}
                browser.close()
        except Exception as exc:  # a render failure is a verdict, not a crash
            return RenderResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        return RenderResult(
            ok=True,
            console_errors=console_errors,
            scroll_width=int(metrics["sw"]),
            client_width=int(metrics["cw"]),
            title=str(metrics["title"]),
            h1_count=int(metrics["h1"]),
            images_total=int(metrics["imgs"]),
            images_without_alt=int(metrics["imgsNoAlt"]),
            buttons_without_label=int(metrics["btnsNoLabel"]),
            selectors_present=present,
            background_luminance=float(metrics["bgLum"]),
            min_contrast=float(metrics["minContrast"]),
            colors=[str(c) for c in metrics["colors"]],
            fonts=[str(f) for f in metrics["fonts"]],
        )
