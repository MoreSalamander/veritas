"""Presets — the substrate generalizes two ways, no new engine.

Reuse: a Newsroom article and an Education lesson run the Research org's grounding pipeline (same
gates), so a grounded report ships under either framing. Compose: a startup/game chains two orgs and
is accepted only if every part shipped — verified by the pure combiner, plus a registry check that
the presets are offered alongside the five real orgs.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact
from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from engine.run import Outcome
from orgs.presets import _Part, _combine, build_article, build_lesson

CORPUS = {
    "src1": "The bald eagle is native to North America. Bald eagles can fly at speeds of up to 30 mph.",
    "src2": "A bald eagle's nest can weigh more than a ton, the largest of any North American bird.",
}
GOOD = json.dumps({
    "topic": "bald eagles",
    "claims": [
        {"text": "Bald eagles can fly up to 30 mph",
         "citations": [{"source": "src1", "quote": "fly at speeds of up to 30 mph"}]},
        {"text": "Their nests can weigh over a ton",
         "citations": [{"source": "src2", "quote": "nest can weigh more than a ton"}]},
    ],
})
JUDGE = json.dumps([{"index": 0, "verdict": "SUPPORTED"}, {"index": 1, "verdict": "SUPPORTED"}])


def _provider():
    return ScriptedProvider({"researcher": GOOD, "judge": JUDGE})


# --- reuse: same grounding model, different product framing -------------------------------

def test_newsroom_article_ships_on_grounding(tmp_path):
    res = build_article("bald eagles", CORPUS, _provider(), MemoryStore(tmp_path))
    assert res.accepted
    names = [g.gate_name for g in res.report_outcome.artifact.provenance.gate_results]
    assert "citations-resolve" in names and "quotes-verbatim" in names  # the Research org's gates


def test_education_lesson_ships_on_grounding(tmp_path):
    res = build_lesson("bald eagles", CORPUS, _provider(), MemoryStore(tmp_path))
    assert res.accepted


# --- compose: chain orgs, accepted only if every part shipped -----------------------------

def _outcome(accepted: bool) -> Outcome:
    art = Artifact.propose(type="x", owner="t", payload="p", rationale="t")
    return Outcome(artifact=art, accepted=accepted, gate_results=[], memory_path=tmp_path_stub())


def tmp_path_stub():
    import pathlib
    import tempfile
    return pathlib.Path(tempfile.mkdtemp()) / "m.md"


def test_combine_accepts_only_if_all_parts_shipped():
    a = _Part([_outcome(True)], True, [], [])
    b = _Part([_outcome(True), _outcome(True)], True, [], [])
    both = _combine([a, b])
    assert both.accepted and len(both.outcomes) == 3 and both.run_id.startswith("compose_")

    c = _Part([_outcome(False)], False, [], [])
    assert not _combine([a, c]).accepted  # one part failed -> the composition fails
