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
from orgs.web_studio.gates import A11yGate, LayoutGate, RenderGate, StructureGate
from orgs.web_studio.spec import PageSpecGate

# (display name, role, what it produces) — proposers; they decide nothing.
_CAST: list[tuple[str, str, str]] = [
    ("Designer", "designer", "Turns a goal into the page's verifiable contract — the elements the page must contain (CSS selectors), not its looks."),
    ("Web Developer", "web-developer", "Turns the contract into a single self-contained HTML document; re-writes on rejection seeing the failing gates (e.g. \"you overflow the viewport\")."),
]

# (gate class, what it checks) — determinism is read from the class itself.
_GATES: list[tuple[type[Gate], str]] = [
    (PageSpecGate, "the spec names what the page must contain — otherwise there's nothing to verify"),
    (RenderGate, "the page loads and runs in a real browser with no console errors"),
    (LayoutGate, "no horizontal overflow — the page fits its viewport (needs a real layout engine)"),
    (StructureGate, "the required elements are present in the rendered DOM — the UI's oracle-free contract"),
    (A11yGate, "the accessibility floor: alt text, button labels, exactly one h1"),
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
        "rendering the page in a real browser — looks are soft and decided elsewhere. Nothing "
        "ships on \"it looks fine.\"",
    }
