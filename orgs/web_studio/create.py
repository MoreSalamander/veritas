"""P21 — create mode: build to the interviewed spec, then the human is the gate.

The pieces converge here. The interview (P20) produced a gateable CreateSpec. The developer
builds HTML to it. The *manufactured* hard gates run — render, structure (the required
elements), and the P19 aesthetic gates (theme/contrast/fonts/palette) — and the developer
self-corrects on any measurable miss, automatically. Only once the measurable bar is met does
a human judge the residue ("does it actually look great?"). Approve → it ships, tagged
human-approved (the third trust tier). Request changes → it re-proposes with your feedback.

The invariant holds: the measurable parts are machine-proven; the feel is human-approved; the
ledger says which is which. Nothing subjective is ever disguised as proven.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from engine.artifact import Artifact, Determinism, GateResult
from engine.memory import MemoryStore
from engine.model import ModelProvider
from engine.run import ActivityEntry, Outcome, Run
from engine.validation import ValidationGate
from orgs.software_studio.agents import _strip_code_fences
from orgs.web_studio.aesthetics import aesthetic_gates
from orgs.web_studio.browser import BrowserExecutor, RenderResult
from orgs.web_studio.gates import RenderGate, StructureGate
from orgs.web_studio.interview import CreateSpec
from orgs.web_studio.profile import ProfileStore, apply_profile

CREATE_DEV_SYSTEM = (
    "You are a front-end developer. Given a spec (required elements + an aesthetic), respond "
    "with ONLY a complete self-contained HTML document — inline CSS and JS, no external "
    "resources. It MUST: contain every required selector; use ONLY the given color palette (set "
    "it on background and text/color); use ONLY the given font(s); honor the theme (dark = dark "
    "background); keep text contrast above the minimum; have exactly one <h1>; give every <img> "
    "alt text and every <button> a label; not overflow horizontally at 1280px; produce no console "
    "errors. CRITICAL — two traps that cause silent rejections: (1) browsers color unstyled "
    "links/nav with a default BLUE that is not in your palette — explicitly set `a{color:...}` to "
    "a palette color for EVERY link and nav item. (2) For body and link text pick the palette "
    "color with the STRONGEST contrast against the background (usually your darkest color on a "
    "light theme, lightest on a dark theme) — do not use a mid-tone accent color as text. "
    "Output ONLY the HTML — no fences, no commentary."
)


@dataclass
class Review:
    """A human's verdict on the soft residue. approved=False carries feedback to iterate on."""

    approved: bool
    feedback: str = ""


ReviewFn = Callable[[str, RenderResult], Review]


class WebCreateDeveloperAgent:
    role = "web-developer"

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def propose(self, spec: CreateSpec, feedback: str | None = None) -> Artifact:
        a = spec.aesthetics
        lines = [
            f"Title: {spec.title}",
            f"Description: {spec.description}",
            f"Required elements (CSS selectors that MUST be present): {', '.join(spec.required_elements)}",
            "Aesthetic:",
        ]
        if a.theme:
            lines.append(f"  theme: {a.theme}")
        if a.min_contrast is not None:
            lines.append(f"  minimum text contrast: {a.min_contrast}")
        if a.fonts:
            lines.append(f"  fonts (use ONLY these): {', '.join(a.fonts)}")
        if a.palette:
            lines.append(f"  palette (use ONLY these colors): {', '.join(a.palette)}")
        prompt = "\n".join(lines)
        if feedback:
            prompt = f"Your previous page was REJECTED: {feedback}\nFix exactly that.\n\n{prompt}"
        raw = self.provider.propose(role=self.role, prompt=prompt, system=CREATE_DEV_SYSTEM)
        return Artifact.propose(
            type="page", owner="web-developer-agent", payload=_strip_code_fences(raw),
            rationale=f"create-mode page: {spec.title}", parent_id="",
        )


@dataclass
class CreatePageResult:
    accepted: bool  # human-approved (and, necessarily, machine-verified first)
    machine_verified: bool  # the hard gates passed on at least one attempt
    page_outcome: Outcome | None  # the persisted, human-approved artifact (None if never approved)
    iterations: int
    run_id: str = ""
    activity: list[ActivityEntry] = field(default_factory=list)


def _hard_feedback(results: list[GateResult]) -> str:
    failed = [
        r for r in results
        if r.determinism is Determinism.HARD and not r.passed and r.gate_name != "validation"
    ]
    return "; ".join(f"{r.gate_name}: {r.evidence}" for r in failed)


def build_create_page(
    spec: CreateSpec, provider: ModelProvider, memory: MemoryStore, review: ReviewFn,
    profile_store: ProfileStore | None = None, max_attempts: int = 4,
) -> CreatePageResult:
    """One loop, two kinds of feedback: a measurable miss re-proposes automatically (hard
    gate evidence); a human 'request changes' re-proposes with the person's words. Only a human
    approval ships the page (and persists it human-approved). When a profile_store is given, the
    learned profile fills the spec's aesthetic gaps first, and a human approval updates it — the
    loop compounds (it learns your taste)."""
    if profile_store is not None:  # fill gaps from learned taste before building
        spec = apply_profile(profile_store.load(), spec)
    run = Run(goal=spec.title, memory=memory)
    executor = BrowserExecutor()
    required = spec.required_elements
    feedback: str | None = None
    machine_verified = False

    for attempt in range(1, max_attempts + 1):
        page = WebCreateDeveloperAgent(provider).propose(spec, feedback=feedback)
        rendered = executor.render(page.payload, required)
        gates = [RenderGate(rendered), StructureGate(rendered, required),
                 *aesthetic_gates(rendered, spec.aesthetics), ValidationGate()]
        results = run.verify(page, gates)  # record verdicts; don't persist a draft
        hard = [r for r in results if r.determinism is Determinism.HARD]
        if not (hard and all(r.passed for r in hard)):
            feedback = _hard_feedback(results)  # measurable miss → fix it automatically
            continue

        machine_verified = True
        verdict = review(page.payload, rendered)  # the human judges the residue
        if verdict.approved:
            human = GateResult(gate_name="human-approval", determinism=Determinism.HUMAN,
                               passed=True, evidence="approved by the human")
            page.record_gate(human)
            outcome = run.persist(page, results + [human])  # ships, tagged human-approved
            if profile_store is not None:  # the approval teaches the profile (the loop compounds)
                prof = profile_store.load()
                prof.update(spec.aesthetics)
                profile_store.save(prof)
            return CreatePageResult(True, True, outcome, attempt, run.id, list(run.log))
        feedback = verdict.feedback  # human-driven refinement

    return CreatePageResult(False, machine_verified, None, max_attempts, run.id, list(run.log))
