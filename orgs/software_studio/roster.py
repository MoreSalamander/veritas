"""The software org's roster, as structured data for the Hub's Org view.

The cast and their descriptions are authored here; each gate's HARD/SOFT determinism is
read straight off the real gate class, so the page can never drift from what the engine
actually does. (If a gate's determinism changes in code, this view changes with it.)
"""

from __future__ import annotations

from typing import Any

from engine.gate import Gate
from engine.validation import ValidationGate
from orgs.software_studio.app import AssemblyGate, E2EGate, E2ESpecGate, EntrypointGate
from orgs.software_studio.gates import (
    AcceptanceGate,
    ConsensusGate,
    ExamplesRunGate,
    PropertyGate,
    QAGate,
    SecurityScanGate,
    SpecScorerGate,
    SyntaxGate,
)
from orgs.software_studio.module import (
    ContractGate,
    IntegrationGate,
    IntegrationSpecGate,
    ModuleAcceptanceGate,
    ModulePropertyGate,
    ModuleSyntaxGate,
)
from orgs.software_studio.plan import PlanGate

# (display name, role, what it produces) — proposers; they decide nothing.
_CAST: list[tuple[str, str, str]] = [
    ("Router", "router", "Picks the pipeline — function, module, or app (a soft pre-decision; whatever it picks is still hard-gated)."),
    ("Spec Agent", "spec", "An executable spec from a goal — name, signature, cases, and oracle-free properties. Prose is rejected."),
    ("Developer Agent", "developer", "The source code from a spec or contract; rewrites on rejection seeing the failing gates' evidence."),
    ("QA Agent", "qa", "Independent edge-case tests written from the spec — without ever seeing the code it reviews."),
    ("Doc Agent", "doc", "Markdown docs whose examples are run against the real function (a role here, not a separate org)."),
    ("Architect Agent", "architect", "A module contract: which functions exist, their signatures, cases, and per-function properties."),
    ("PM Agent", "pm", "Acceptance as executable relational tests; at app scale, designs main()'s contract."),
    ("Planner Agent", "planner", "A plan for a goal too big for one module — a list of module briefs. No code."),
    ("Integrator Agent", "integrator", "The app entrypoint main() that composes the modules to satisfy the end-to-end tests."),
]

# (gate class, scope, what it checks) — determinism is read from the class itself.
_GATES: list[tuple[type[Gate], str, str]] = [
    (SpecScorerGate, "function", "the spec is executable (has cases or properties)"),
    (SyntaxGate, "function", "parses and defines the named function"),
    (PropertyGate, "function", "oracle-free relations hold (round-trip, monotonic, invariant, idempotent) — the behavioral authority"),
    (AcceptanceGate, "function", "exact-value cases — a model-authored oracle, so advisory only"),
    (SecurityScanGate, "function", "deterministic static scan for dangerous calls — no LLM"),
    (QAGate, "function", "QA's independent cases (its oracle is also an LLM, so advisory)"),
    (ConsensusGate, "function", "a voting oracle's graded confidence for the value gap properties can't reach (opt-in)"),
    (ExamplesRunGate, "function", "every documentation example actually runs against the real code"),
    (ContractGate, "module", "the module contract is usable (at least two functions)"),
    (IntegrationSpecGate, "module", "the PM's tests exercise at least two functions together"),
    (ModuleSyntaxGate, "module", "every function named in the contract is defined"),
    (ModulePropertyGate, "module", "per-function oracle-free relations — round-trip goes hard here (the inverse is in scope)"),
    (ModuleAcceptanceGate, "module", "per-function exact-value cases — advisory"),
    (IntegrationGate, "module", "the functions work together, not just alone"),
    (PlanGate, "app", "the plan is a usable multi-module decomposition"),
    (AssemblyGate, "app", "the modules coexist — no name clashes, loads clean"),
    (EntrypointGate, "app", "main() is defined and loads with the package"),
    (E2ESpecGate, "app", "the end-to-end tests actually drive main()"),
    (E2EGate, "app", "the whole app runs end to end"),
    (ValidationGate, "all", "final authority: every hard gate passed, provenance complete"),
]


def roster() -> dict[str, Any]:
    return {
        "cast": [{"name": n, "role": r, "produces": p} for n, r, p in _CAST],
        "gates": [
            {"name": g.name, "determinism": g.determinism.value, "scope": scope, "about": about}
            for g, scope, about in _GATES
        ],
        "principle": "A run with zero HARD gates can never accept anything. The cast can be as "
        "persuasive as it likes — nothing reaches memory on judgment alone.",
    }
