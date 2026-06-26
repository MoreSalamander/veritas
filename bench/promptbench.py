#!/usr/bin/env python
"""Prompt-bench — does a change to a proposer's PROMPT move the VERIFIED bar, reproducibly?

The bootstrap question (the strange loop): Veritas's own proposers are driven by system prompts
(`SPEC_SYSTEM`, `DEV_SYSTEM`, …). Can we *improve a prompt* and prove the improvement the org's own
way — by accept-rate through the unchanged HARD gates — rather than by a model grading the prompt
(which is the collusion the standalone "prompt polish" tools commit)?

This is the measurement that must come BEFORE any prompt studio: it asks whether a prompt delta
produces a real, reproducible accept-rate signal, or just noise. It is the prompt analogue of
`run_bench.py` — same builds, same gates, but the *prompt* is the variable instead of the model.

It A/Bs N named variants of one proposer's system prompt across a fixed goal set. The default
experiment varies `SPEC_SYSTEM` three ways, with two guards built in:
  * **baseline** — the live prompt.
  * **cosmetic** — a meaning-preserving reword. A real signal must NOT move this (else the bench is
    rewarding *any* change, not quality).
  * **vague** — a realistic under-specification (drops the schema field names + property guidance, the
    kind of prompt a non-expert would write). If prompt quality matters here, this should drop accept-rate.

Verdict: signal is real and usable iff baseline ≈ cosmetic AND baseline > vague, reproducibly. If a
big realistic degradation doesn't move the bar, prompt-tuning-by-accept-rate is faint at this scale —
a finding that steers the studio toward marginal tasks (a model at its ceiling or floor can't show a
prompt delta). Run:  .venv/bin/python bench/promptbench.py [--model qwen-9b] [--repeats 2]
"""

from __future__ import annotations

import argparse
import pathlib
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.memory import MemoryStore  # noqa: E402
from engine.model import OllamaProvider  # noqa: E402
from orgs.software_studio import agents  # noqa: E402  (we override a module-level prompt per variant)
from orgs.software_studio.builder import build  # noqa: E402

# model_key -> (ollama model name). Temperature is set per-run from --temp so we can drive variance
# to ~0 and isolate the prompt's effect from sampling noise.
MODEL_NAMES = {"qwen-9b": "qwen3.5:9b", "gemma-12b": "gemma4:12b", "llama-8b": "llama3.1:8b"}

GOALS = [
    ("reverse", "a function that reverses a string"),
    ("clamp", "a function that clamps a number to be at least zero"),
    ("double", "a function that doubles a number"),
]

# The live prompt is captured ONCE, here, before any override — every variant is derived from this,
# never from the (mutated) module attribute.
_BASELINE = agents.SPEC_SYSTEM

# A meaning-preserving reword of the opening line — the neutral control.
_COSMETIC = _BASELINE.replace(
    "You are a precise software specification writer.",
    "You are a careful and precise author of software specifications.",
)
if _COSMETIC == _BASELINE:
    sys.exit("cosmetic reword found no anchor — SPEC_SYSTEM changed; update the bench.")

# A realistic under-specification: keeps "JSON only" but drops the exact schema field names and the
# whole property-guidance block — the kind of prompt someone writes before they know what the gates need.
_VAGUE = (
    "You are a software specification writer. Given a goal, respond with ONLY a JSON object "
    "describing the Python function to build — its name, a short description, the signature, and a "
    "few example input/output cases. No prose, no markdown, no code fences."
)

VARIANTS: dict[str, str] = {"baseline": _BASELINE, "cosmetic": _COSMETIC, "vague": _VAGUE}


def _run(goal: str, make_provider) -> dict:
    t0 = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory() as d:  # isolated memory: no cross-run learning
            res = build(goal, make_provider(), MemoryStore(pathlib.Path(d)))
        retries = len([e for e in res.activity if e.actor == "retry"])
        return {"accepted": res.accepted, "retries": retries, "time": time.perf_counter() - t0}
    except Exception as exc:  # a crashed build is a non-accept, recorded honestly
        return {"accepted": False, "retries": 0, "time": time.perf_counter() - t0, "error": str(exc)[:80]}


def _rate(runs: list[dict]) -> float:
    return sum(r["accepted"] for r in runs) / len(runs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen-9b", choices=list(MODEL_NAMES))
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--temp", type=float, default=0.2, help="proposer temperature (0 = isolate prompt from sampling noise)")
    args = ap.parse_args()
    name = MODEL_NAMES[args.model]
    make_provider = lambda: OllamaProvider(model=name, think=False, timeout=300, temperature=args.temp)

    print(f"prompt-bench · SPEC_SYSTEM variants · {args.model} · temp={args.temp} · {args.repeats}x each\n", flush=True)
    cells: dict[str, dict[str, list[dict]]] = {}
    try:
        for vlabel, prompt in VARIANTS.items():
            agents.SPEC_SYSTEM = prompt  # the override IS the experiment
            cells[vlabel] = {}
            for gkey, goal in GOALS:
                runs = [_run(goal, make_provider) for _ in range(args.repeats)]
                cells[vlabel][gkey] = runs
                print(f"  [{vlabel:9}] {gkey:8} accept={_rate(runs):.0%}  "
                      f"mean {statistics.mean(r['time'] for r in runs):.0f}s", flush=True)
    finally:
        agents.SPEC_SYSTEM = _BASELINE  # always restore the live prompt

    overall = {v: statistics.mean(_rate(cells[v][g]) for g, _ in GOALS) for v in VARIANTS}
    print("\n--- overall accept-rate by variant ---")
    for v in VARIANTS:
        print(f"  {v:9} {overall[v]:.0%}")

    print("\n--- the verdict ---")
    cosmetic_moved = abs(overall["baseline"] - overall["cosmetic"]) > 1e-9
    vague_dropped = overall["baseline"] - overall["vague"] > 1e-9
    if vague_dropped and not cosmetic_moved:
        print("  SIGNAL IS REAL AND SPECIFIC — a realistic degradation dropped accept-rate, a cosmetic "
              "reword did not. Prompt quality moves the verified bar here; the studio is worth building.")
    elif vague_dropped and cosmetic_moved:
        print("  signal present but NOISY — the cosmetic control moved too; needs more repeats / a "
              "cleaner goal set before the signal can be trusted.")
    else:
        print("  NO SIGNAL at this scale — even a vague prompt cleared the same gates (the deterministic "
              "floor + concrete cases absorb the degradation, or the goals sit at the model's ceiling). "
              "A prompt studio needs MARGINAL tasks to show a delta — that is the real finding.")

    out = ROOT / "bench" / "results" / f"promptbench_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Prompt-bench — SPEC_SYSTEM variants", "",
             f"_{datetime.now(timezone.utc).isoformat()} · {args.model} · {args.repeats}x each_", "",
             "| variant | " + " | ".join(g for g, _ in GOALS) + " | overall |",
             "|---|" + "---|" * (len(GOALS) + 1)]
    for v in VARIANTS:
        row = " | ".join(f"{_rate(cells[v][g]):.0%}" for g, _ in GOALS)
        lines.append(f"| {v} | {row} | {overall[v]:.0%} |")
    out.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
