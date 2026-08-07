"""The Research Intelligence layer: plan, then acquire in parallel.

Two pieces, both deliberately deterministic at the edges:

* **ResearchPlan** — the planner agent proposes a plan (domain, questions,
  angles, unknowns) as JSON; ``parse_plan`` is the deterministic contract.
  Angles come from a CLOSED vocabulary — each angle is a real acquisition
  strategy (query bias + source preference), not a costume. An angle we
  don't implement is an angle the parser refuses.

* **Parallel acquisition** — one worker per planned angle, fanned out
  concurrently over the live search seam (asyncio around the synchronous
  SearchClient; real parallel I/O, honestly capped). Every corpus entry
  carries its angle and URL so citations stay traceable end to end and the
  verbatim-quote gate has full text to check against.

The planner proposes; the parser decides; the workers fetch; the gates
still rule the report. Same doctrine, bigger reach.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the seam type, for signatures only
    from commons.parallel_client import SearchClient


class PlanParseError(ValueError):
    """The proposed research plan is not usable."""


# The closed angle vocabulary: name -> (query bias appended to the topic,
# one-line charter shown in the plan). Specialization is a real search
# strategy; adding an angle here is how breadth grows honestly.
ANGLES: dict[str, tuple[str, str]] = {
    "academic": ("research paper arxiv study", "Peer-reviewed and preprint findings."),
    "industry": ("industry announcement roadmap vendor", "What the builders are shipping and claiming."),
    "news": ("news 2025 2026", "Current reporting and recent developments."),
    "code": ("github open source implementation", "What exists as running code."),
    "patents": ("patent filing uspto", "What is being claimed as invention."),
    "market": ("market size forecast adoption", "Money, adoption, and trajectory."),
    "community": ("reddit forum discussion experience", "Practitioner experience and dissent."),
    "history": ("history origin evolution of", "How this field got here."),
    "regulation": ("regulation policy compliance law", "The rules closing in around it."),
    "documentation": ("documentation spec technical reference", "The primary technical record."),
}

_MAX_ANGLES = 6
_MAX_QUESTIONS = 8


@dataclass
class ResearchPlan:
    """What the engine intends to find out, and from which directions."""

    topic: str
    domain: str
    questions: list[str]
    angles: list[str]
    unknowns: list[str] = field(default_factory=list)

    def brief(self) -> str:
        lines = [
            f"RESEARCH PLAN — {self.topic}",
            f"- domain: {self.domain}",
            "- questions: " + "; ".join(self.questions),
            "- angles: " + ", ".join(
                f"{a} ({ANGLES[a][1]})" for a in self.angles
            ),
        ]
        if self.unknowns:
            lines.append("- known unknowns: " + "; ".join(self.unknowns))
        return "\n".join(lines)


def parse_plan(payload: str, topic: str) -> ResearchPlan:
    """The deterministic contract on the planner's proposal."""
    start, end = payload.find("{"), payload.rfind("}")
    if start == -1 or end <= start:
        raise PlanParseError("no JSON object in plan output")
    try:
        obj: Any = json.loads(payload[start : end + 1])
    except (ValueError, TypeError) as exc:
        raise PlanParseError(f"plan is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise PlanParseError("plan must be a JSON object")

    questions = [str(q).strip() for q in (obj.get("questions") or []) if str(q).strip()]
    if not questions:
        raise PlanParseError("plan has no research questions")
    angles_raw = [str(a).strip().lower() for a in (obj.get("angles") or []) if str(a).strip()]
    unknown_angles = [a for a in angles_raw if a not in ANGLES]
    if unknown_angles:
        raise PlanParseError(
            f"unknown angle(s) {unknown_angles} — the vocabulary is {sorted(ANGLES)}"
        )
    # De-dupe preserving order; cap honestly rather than pretending we'll run 10.
    seen: list[str] = []
    for a in angles_raw:
        if a not in seen:
            seen.append(a)
    if not seen:
        raise PlanParseError("plan names no angles")
    return ResearchPlan(
        topic=topic,
        domain=str(obj.get("domain") or "").strip() or "general",
        questions=questions[:_MAX_QUESTIONS],
        angles=seen[:_MAX_ANGLES],
        unknowns=[str(u).strip() for u in (obj.get("unknowns") or []) if str(u).strip()][:8],
    )


@dataclass
class AcquiredSource:
    """One fetched source, tagged with the angle that went looking for it."""

    url: str
    title: str
    content: str
    angle: str

    def corpus_entry(self) -> str:
        return f"SOURCE: {self.url}\nANGLE: {self.angle}\n{self.title}\n\n{self.content}"


def acquire_parallel(
    plan: ResearchPlan,
    search_client: "SearchClient",
    *,
    per_angle: int = 3,
    concurrency: int = 6,
) -> list[AcquiredSource]:
    """Fan the plan's angles out over the live search seam concurrently.

    The SearchClient is synchronous; each worker runs it in a thread via
    asyncio, so the I/O genuinely overlaps. One dead angle or URL never
    sinks the haul — workers fail independently and honestly return
    nothing. De-duplication is by URL across angles: the first angle to
    fetch a page keeps it.
    """

    async def _run() -> list[AcquiredSource]:
        sem = asyncio.Semaphore(concurrency)

        async def fetch_angle(angle: str) -> list[AcquiredSource]:
            bias, _charter = ANGLES[angle]
            query = f"{plan.topic} {bias}"
            try:
                async with sem:
                    results = await asyncio.to_thread(
                        search_client.search, query, per_angle
                    )
            except Exception:
                return []
            out: list[AcquiredSource] = []
            for r in results:
                try:
                    async with sem:
                        ex = await asyncio.to_thread(
                            search_client.extract, r.url, objective=plan.topic
                        )
                except Exception:
                    continue  # one dead URL never sinks the haul
                if ex.content.strip():
                    out.append(
                        AcquiredSource(url=ex.url, title=ex.title, content=ex.content, angle=angle)
                    )
            return out

        batches = await asyncio.gather(*(fetch_angle(a) for a in plan.angles))
        seen_urls: set[str] = set()
        merged: list[AcquiredSource] = []
        for batch in batches:
            for src in batch:
                if src.url in seen_urls:
                    continue
                seen_urls.add(src.url)
                merged.append(src)
        return merged

    return asyncio.run(_run())
