"""The Web Studio's roster, as structured data for the Hub's Org view.

Same shape as the software org's roster: the cast is authored here, each gate's HARD/SOFT
determinism is read straight off the real gate class so the page can never drift from what
the engine actually does. Note the gates are *all* HARD right now — a UI's structural floor
is fully deterministic. Aesthetics (a soft gate) join later; that's the only judgment in the
domain, and it will be honestly marked soft.
"""

from __future__ import annotations

from typing import Any

from engine.gate import Gate
from engine.validation import ValidationGate
from orgs.web_studio.gates import A11yGate, AxeGate, LayoutGate, RenderGate, StructureGate
from orgs.web_studio.spec import PageSpecGate

# (display name, role, what it produces) — proposers; they decide nothing.
_CAST: list[tuple[str, str, str]] = [
    ("UX Researcher", "designer", "Decomposes a site request into the design brief: industry, audience, brand qualities, goals, pages (closed vocabulary), and the semantic intents the design researchers hunt with."),
    ("Design Researchers", "acquisition", "Angle workers (award winners, enterprise SaaS, competitors, component patterns, typography & color, conversion, accessibility exemplars) fetching live design sources in parallel; every source lands angle-tagged."),
    ("Design Director", "designer", "Synthesizes a NEW design system from the corpus — validated palette, font stacks, closed layout & component vocabularies — with every influence citing its corpus source. Synthesis over copying, parse-enforced."),
    ("Designer", "designer", "Turns a page's build order into the verifiable contract — the elements the page must contain (CSS selectors), not its looks."),
    ("Web Developer", "web-developer", "Turns the contract into a single self-contained HTML document; re-writes on rejection seeing the failing gates (e.g. \"you overflow the viewport\")."),
]

# (gate class, what it checks) — determinism is read from the class itself.
_GATES: list[tuple[type[Gate], str]] = [
    (PageSpecGate, "the spec names what the page must contain — otherwise there's nothing to verify"),
    (RenderGate, "the page loads and runs in a real browser with no console errors"),
    (LayoutGate, "no horizontal overflow — the page fits its viewport (needs a real layout engine)"),
    (StructureGate, "the required elements are present in the rendered DOM — the UI's oracle-free contract"),
    (A11yGate, "the accessibility floor: alt text, button labels, exactly one h1"),
    (AxeGate, "AccessGuard folded in: axe-core WCAG rules against the rendered DOM — zero critical/serious violations, the AccessGuard impact-weighted score on the evidence"),
    (ValidationGate, "final authority: every hard gate passed, provenance complete"),
]


def roster() -> dict[str, Any]:
    return {
        "cast": [{"name": n, "role": r, "produces": p} for n, r, p in _CAST],
        "gates": [
            {"name": g.name, "determinism": g.determinism.value, "scope": "page", "about": about}
            for g, about in _GATES
        ],
        "principle": "A UI's structure is a fact, not a taste. Everything here is hard-verified by "
        "rendering the page in a real browser — WCAG included, via the same axe-core engine "
        "AccessGuard runs. Site-level gates (nav-links-resolve, design-system consistency) hold "
        "whole sites to one standard. Nothing ships on \"it looks fine.\"",
    }
