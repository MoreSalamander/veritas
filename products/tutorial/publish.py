"""Mirrors a dispensed tutorial into myAIstro's real SOT — best-effort, never the source of
truth. Veritas persists its own copy of every product the moment its gate passes (see
tutorial_record in hub/tutorial_generate.py); this write is a downstream extension myAIstro
happens to consume, the same relationship the Obsidian vault has to Veritas's own memory, not a
place Veritas's own data or code lives.

Uses the exact write path proven live for DATAHUB101 (create_lesson_ingest_event ->
write_to_memory). myAIstro's own lesson shape is flatter than the manual shape this module
generates (materials/sections/steps), so the content gets adapted on the way in — that adaptation
lives HERE, in the seam that talks to myAIstro, not upstream in the shape Veritas itself keeps.
code from steps (when the spec asked for typing practice) flows into myAIstro's own code_blocks
field, which its Classroom pipeline already turns into real TYPING_PRACTICE beats
(agents/teacher_aide_agent.py) — proven, not assumed.

Deliberately a thin function, not a class: this is a one-shot write, the same shape as
scripts/import_myaistro_lessons.py and the DATAHUB101 ingest script, not a service.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from engine.memory import MemoryRecord
from products.tutorial.generate import TutorialContent
from products.tutorial.spec import TutorialSpec

MYAISTRO_BACKEND = Path.home() / "myAIstro" / "backend"


def publish_tutorial(
    source: MemoryRecord, content: TutorialContent, spec: TutorialSpec, course: str = "TUTORIALS",
) -> dict[str, Any]:
    """Writes one tutorial into myAIstro's memory_store.json as a real lesson. `source` is the
    Knowledge Graph record the tutorial was generated from; its title becomes the lesson title
    and its own id keys the week, so re-running for the same source replaces rather than
    duplicates (myAIstro's own upsert-on-(course,week,lesson) semantics)."""
    if str(MYAISTRO_BACKEND) not in sys.path:
        sys.path.insert(0, str(MYAISTRO_BACKEND))
    # myAIstro is a sibling repo, not a dependency mypy can resolve statically — the sys.path
    # insert above makes it importable at runtime; these two ignores are that seam, not laziness.
    from core.event_schema import create_lesson_ingest_event  # type: ignore[import-not-found]  # noqa: E402
    from core.memory_writer_node import write_to_memory  # type: ignore[import-not-found]  # noqa: E402

    event = create_lesson_ingest_event(
        course=course,
        week=source.id,  # one source -> one stable "week" slot, so re-generating replaces it
        lesson=source.title,
        raw_text=source.body,
    )
    result: dict[str, Any] = write_to_memory(
        event,
        summary_data=_adapt_to_myaistro_lesson(content),
        validation_data={"validation": "PASS", "score": 1},
    )
    return result


def _adapt_to_myaistro_lesson(content: TutorialContent) -> dict[str, Any]:
    """myAIstro's lesson shape is flatter (summary/key_concepts/definitions/code_blocks) than the
    manual shape Veritas keeps (overview/materials/sections-of-steps) — this is the one place that
    gap gets bridged, so it can change independently of what Veritas itself generates and stores."""
    key_concepts = [f"{sec.title}: {sec.intro}" if sec.intro else sec.title for sec in content.sections]
    definitions = [f"Needed — {m}" for m in content.materials]
    code_blocks = [s.code for sec in content.sections for s in sec.steps if s.code]
    return {
        "summary": content.overview,
        "key_concepts": key_concepts,
        "definitions": definitions,
        "code_blocks": code_blocks,
        "mastery_goals": [],
    }


if __name__ == "__main__":
    import argparse

    from engine.memory import default_memory_store
    from engine.model import OllamaProvider
    from products.tutorial.generate import generate_tutorial

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True, help="a Knowledge Graph record id, e.g. mem_abc123")
    parser.add_argument("--depth", default="walkthrough", choices=["overview", "walkthrough", "deep_dive"])
    parser.add_argument("--reading-style", default="detailed", choices=["essentials_only", "detailed"])
    parser.add_argument("--typing-practice", action="store_true")
    args = parser.parse_args()

    commons = default_memory_store(Path(__file__).resolve().parent.parent / "hub_data" / "memory" / "commons")
    matches = [r for r in commons.load_all() if r.id == args.source_id]
    if not matches:
        raise SystemExit(f"no Knowledge Graph record with id {args.source_id!r}")
    source = matches[0]

    spec = TutorialSpec(
        depth=args.depth, reading_style=args.reading_style,
        include_typing_practice=args.typing_practice,
    )
    provider = OllamaProvider(model="gemma4:12b")
    artifact, result = generate_tutorial(source, spec, provider)
    print(f"gate: {'PASS' if result.passed else 'FAIL'} — {result.evidence}", file=sys.stderr)
    if not result.passed:
        raise SystemExit(1)

    from products.tutorial.generate import parse_tutorial_content

    content = parse_tutorial_content(artifact.payload)
    outcome = publish_tutorial(source, content, spec)
    print(f"published: {outcome}", file=sys.stderr)
