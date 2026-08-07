"""The Design Intelligence layer: the web studio becomes an agency.

The same spine the Research Intelligence engine proved yesterday, wearing
design vocabulary — because the vision compounds and the machinery is
shared (`fan_out` lives in research_studio.intelligence; both engines ride
it). Three deterministic contracts hold the whole thing:

* **DesignBrief** — user intent, decomposed: industry, audience, brand
  qualities, goals, the site's pages (CLOSED page vocabulary), and the
  semantic design intents the researchers hunt with. A page type we can't
  build is a page type the parser refuses.

* **Design acquisition** — angle workers with design charters (award
  winners, enterprise SaaS, competitors, component patterns, typography &
  color, conversion, accessibility exemplars) fanned out in parallel;
  every source lands angle-tagged.

* **DesignSystem** — the synthesis contract: validated hex palette, font
  stacks, a CLOSED layout & component vocabulary, and ``inspired_by``
  entries that MUST cite corpus sources. Synthesis over copying is not a
  slogan here; an influence that can't name its source is refused.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from orgs.research_studio.intelligence import AcquiredSource, fan_out

if TYPE_CHECKING:
    from commons.parallel_client import SearchClient


class BriefParseError(ValueError):
    """The proposed design brief is not usable."""


class DesignSystemParseError(ValueError):
    """The proposed design system is not usable."""


# The pages this studio knows how to gate. A brief naming anything else is
# refused — we never promise a page type the wall can't rule on.
PAGE_TYPES: dict[str, str] = {
    "landing": "the front door: hero, value, proof, call to action",
    "product": "what it does, shown concretely",
    "about": "who is behind it and why they're credible",
    "pricing": "plans and the decision moment",
    "contact": "how to reach a human",
    "docs": "the technical record, navigable",
    "faq": "objections, answered plainly",
    "blog": "the writing surface",
}

# Design research angles: semantic-intent query bias + charter.
DESIGN_ANGLES: dict[str, tuple[str, str]] = {
    "award_winners": ("award winning website design awwwards showcase", "What the field celebrates right now."),
    "enterprise_saas": ("enterprise saas website design examples", "How credibility looks at contract size."),
    "startup_landing": ("startup landing page design best examples", "How new things earn attention fast."),
    "competitors": ("companies websites in", "What the user's rivals are actually shipping."),
    "component_patterns": ("website hero pricing testimonial section design patterns", "The reusable anatomy of pages."),
    "typography_color": ("website typography color palette system design", "The systems under the surfaces."),
    "conversion": ("landing page conversion design patterns evidence", "What measurably moves visitors."),
    "accessibility": ("accessible website design wcag exemplary", "Designs that include everyone."),
}

# The components the generator can build AND the wall can check — each maps
# to CSS selectors the StructureGate verifies on the real rendered DOM.
COMPONENTS: dict[str, list[str]] = {
    "nav": ["nav"],
    "hero": ["header, .hero"],
    "features": [".features, .feature, section"],
    "testimonials": [".testimonials, .testimonial, blockquote"],
    "logo_wall": [".logos, .logo-wall"],
    "pricing_table": [".pricing, .plans, table"],
    "product_demo": [".demo, .product, figure"],
    "stats": [".stats, .metrics"],
    "team": [".team"],
    "faq_list": [".faq, details"],
    "cta": [".cta, .call-to-action"],
    "footer": ["footer"],
}

LAYOUTS = (
    "enterprise_saas", "startup_hero", "editorial", "dark_technical",
    "portfolio", "playful_consumer",
)

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_PAGES = 5


@dataclass
class DesignBrief:
    """Phase 1: user intent, decomposed into buildable facts."""

    goal: str
    industry: str
    audience: list[str]
    brand_qualities: list[str]
    user_goals: list[str]
    pages: list[str]
    design_intents: list[str]

    def brief(self) -> str:
        return "\n".join([
            f"DESIGN BRIEF — {self.goal}",
            f"- industry: {self.industry}",
            "- audience: " + ", ".join(self.audience),
            "- brand must communicate: " + ", ".join(self.brand_qualities),
            "- user goals: " + ", ".join(self.user_goals),
            "- pages: " + ", ".join(self.pages),
            "- research intents: " + "; ".join(self.design_intents),
        ])


def parse_design_brief(payload: str, goal: str) -> DesignBrief:
    obj = _extract_obj(payload, BriefParseError)
    pages_raw = [str(p).strip().lower() for p in (obj.get("pages") or []) if str(p).strip()]
    unknown = [p for p in pages_raw if p not in PAGE_TYPES]
    if unknown:
        raise BriefParseError(
            f"unknown page type(s) {unknown} — this studio builds {sorted(PAGE_TYPES)}"
        )
    if not pages_raw:
        raise BriefParseError("brief names no pages")
    pages: list[str] = []
    for pg in pages_raw:
        if pg not in pages:
            pages.append(pg)
    if "landing" in pages:  # the front door leads, whatever order the model chose
        pages.remove("landing")
        pages.insert(0, "landing")
    intents = [str(i).strip() for i in (obj.get("design_intents") or []) if str(i).strip()]
    if not intents:
        raise BriefParseError("brief has no design intents to research with")
    return DesignBrief(
        goal=goal,
        industry=str(obj.get("industry") or "").strip() or "general",
        audience=_strs(obj.get("audience")),
        brand_qualities=_strs(obj.get("brand_qualities")),
        user_goals=_strs(obj.get("user_goals")),
        pages=pages[:_MAX_PAGES],
        design_intents=intents[:6],
    )


@dataclass
class Influence:
    """One attributed inspiration: which corpus source, which pattern taken."""

    source: str
    pattern: str


@dataclass
class DesignSystem:
    """Phase 5: the synthesis — a buildable system, every influence named."""

    layout: str
    palette: dict[str, str]           # bg / surface / ink / accent (+accent2) as hex
    heading_font: str                 # a CSS font stack
    body_font: str
    components_by_page: dict[str, list[str]]
    inspired_by: list[Influence] = field(default_factory=list)
    rationale: str = ""

    def css_variables(self) -> str:
        """The shared skin every page must carry — the consistency gate
        checks for these exact declarations."""
        parts = [f"--{k}: {v};" for k, v in sorted(self.palette.items())]
        return ":root { " + " ".join(parts) + " }"

    def brief(self) -> str:
        lines = [
            f"DESIGN SYSTEM — layout: {self.layout}",
            "- palette: " + ", ".join(f"{k} {v}" for k, v in sorted(self.palette.items())),
            f"- type: headings '{self.heading_font}' · body '{self.body_font}'",
        ]
        for page, comps in self.components_by_page.items():
            lines.append(f"- {page}: " + ", ".join(comps))
        for inf in self.inspired_by:
            lines.append(f"- inspired by {inf.source}: {inf.pattern}")
        if self.rationale:
            lines.append(f"- rationale: {self.rationale}")
        return "\n".join(lines)


_REQUIRED_PALETTE = ("bg", "surface", "ink", "accent")


def parse_design_system(
    payload: str, brief: DesignBrief, corpus_ids: set[str]
) -> DesignSystem:
    """The deterministic contract on the synthesis. Layout and components
    come from closed vocabularies; palette entries are real hex; every
    influence must cite a source id that exists in the design corpus —
    synthesis with provenance, or refusal."""
    obj = _extract_obj(payload, DesignSystemParseError)

    layout = str(obj.get("layout") or "").strip().lower()
    if layout not in LAYOUTS:
        raise DesignSystemParseError(f"layout {layout!r} not in {LAYOUTS}")

    palette_raw = obj.get("palette") or {}
    palette: dict[str, str] = {}
    for key, value in palette_raw.items() if isinstance(palette_raw, dict) else []:
        if not _HEX.match(str(value).strip()):
            raise DesignSystemParseError(f"palette {key!r} is not a #rrggbb hex: {value!r}")
        palette[str(key).strip()] = str(value).strip().lower()
    missing = [k for k in _REQUIRED_PALETTE if k not in palette]
    if missing:
        raise DesignSystemParseError(f"palette missing {missing} (need {_REQUIRED_PALETTE})")

    comps_raw = obj.get("components_by_page") or {}
    if not isinstance(comps_raw, dict) or not comps_raw:
        raise DesignSystemParseError("components_by_page must map every page to components")
    components_by_page: dict[str, list[str]] = {}
    for page in brief.pages:
        page_comps = [str(c).strip().lower() for c in (comps_raw.get(page) or [])]
        unknown = [c for c in page_comps if c not in COMPONENTS]
        if unknown:
            raise DesignSystemParseError(
                f"page {page!r} names unknown component(s) {unknown} — vocabulary: {sorted(COMPONENTS)}"
            )
        if not page_comps:
            raise DesignSystemParseError(f"page {page!r} has no components")
        for required in ("nav", "footer"):
            if required not in page_comps:
                page_comps.append(required)  # every page carries the frame
        components_by_page[page] = page_comps

    inspired: list[Influence] = []
    for i, inf in enumerate(obj.get("inspired_by") or []):
        if not isinstance(inf, dict):
            raise DesignSystemParseError(f"inspired_by {i} must be an object")
        src = str(inf.get("source") or "").strip()
        if src not in corpus_ids:
            raise DesignSystemParseError(
                f"inspired_by {i} cites {src!r}, which is not in the design corpus — "
                "an influence that can't name its source is refused"
            )
        inspired.append(Influence(source=src, pattern=str(inf.get("pattern") or "").strip()))

    heading = str(obj.get("heading_font") or "").strip()
    body = str(obj.get("body_font") or "").strip()
    if not heading or not body:
        raise DesignSystemParseError("heading_font and body_font are required CSS stacks")

    return DesignSystem(
        layout=layout, palette=palette, heading_font=heading, body_font=body,
        components_by_page=components_by_page, inspired_by=inspired,
        rationale=str(obj.get("rationale") or "").strip(),
    )


def acquire_design_corpus(
    brief: DesignBrief,
    search_client: "SearchClient",
    *,
    angles: list[str] | None = None,
    per_angle: int = 2,
    concurrency: int = 6,
) -> list[AcquiredSource]:
    """Design research: semantic intents + angle charters become parallel
    queries over the shared fan-out engine."""
    chosen = angles or ["award_winners", "enterprise_saas", "competitors", "component_patterns"]
    intent = "; ".join(brief.design_intents[:3])
    queries: dict[str, str] = {}
    for angle in chosen:
        if angle not in DESIGN_ANGLES:
            continue
        bias, _charter = DESIGN_ANGLES[angle]
        if angle == "competitors":
            queries[angle] = f"{bias} {brief.industry}"
        else:
            queries[angle] = f"{bias} — {intent}"
    return fan_out(
        queries, search_client,
        objective=f"design research for: {brief.goal}",
        per_angle=per_angle, concurrency=concurrency,
    )


def _extract_obj(payload: str, err: type[ValueError]) -> dict[str, Any]:
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        raise err("no JSON object found")
    try:
        obj = json.loads(payload[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise err(f"not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise err("must be a JSON object")
    return obj


def _strs(value: Any) -> list[str]:
    return [str(v).strip() for v in (value or []) if str(v).strip()][:6]
