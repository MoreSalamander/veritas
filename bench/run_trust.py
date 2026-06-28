"""P30c — run the trust benchmark against real models and report.

Hands the curated battery (P30b) to a real model as both contestants — bare agent (one proposal,
shipped) and Veritas (gated) — judged by the independent oracle, repeated N times so the finding is
reproducible (the Empirical-org discipline: a claim ships only if a re-run supports it). Prints a
results table and writes bench/TRUST_RESULTS.md.

    python -m bench.run_trust --models gemma-12b,qwen-9b --repeats 3
    python -m bench.run_trust --models sonnet --repeats 1     # cloud — costs a few cents/build

Local models are free but slow; a full battery (10 tasks x 2 contestants) is ~20 builds per repeat.
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path

from engine.memory import MemoryStore
from engine.model import ModelProvider
from bench.run_bench import MODELS  # reuses the .env load + provider factories
from bench.trust_bench import BatteryResult, run_battery
from bench.trust_tasks import battery_tasks


def run_model(factory, repeats: int = 1, mem_root: str | None = None) -> list[BatteryResult]:
    """Run the whole battery `repeats` times through one model (a fresh provider per repeat)."""
    base = Path(mem_root or tempfile.mkdtemp(prefix="trust_"))
    out: list[BatteryResult] = []
    for r in range(repeats):
        provider: ModelProvider = factory()
        items = [(t, provider) for t in battery_tasks()]
        counter = itertools.count()
        out.append(run_battery(items, lambda: MemoryStore(base / f"r{r}_{next(counter)}")))
    return out


@dataclass
class ModelSummary:
    model: str
    repeats: int
    bare_false_ship: float        # mean rate across repeats
    veritas_false_ship: float
    veritas_over_refusal: float
    catchable_bare_false: float   # mean false-ship COUNT within the catchable class
    catchable_veritas_false: float
    reproducible: bool            # the finding (bare ≥ veritas on catchable false-ships) held EVERY repeat


def summarize(model: str, results: list[BatteryResult]) -> ModelSummary:
    mean = statistics.mean
    cb = [r.catchable_false_ships()[0] for r in results]
    cv = [r.catchable_false_ships()[1] for r in results]
    # reproducible = in every repeat the bare agent false-shipped at least as many catchable-wrong
    # answers as Veritas, and Veritas never false-shipped MORE than bare (the qualitative claim holds).
    reproducible = all(b >= v for b, v in zip(cb, cv))
    return ModelSummary(
        model, len(results),
        mean(r.bare.false_ship_rate for r in results),
        mean(r.veritas.false_ship_rate for r in results),
        mean(r.veritas.over_refusal_rate for r in results),
        mean(cb), mean(cv), reproducible,
    )


def format_markdown(summaries: list[ModelSummary]) -> str:
    lines = [
        "# Trust benchmark (P30) — does the gate architecture refuse what a bare agent ships?",
        "",
        f"Same model, two contestants; an independent oracle judges. Battery: {len(battery_tasks())} tasks "
        "(easy / catchable / uncatchable). The headline is the **catchable** class: false-ships the bare "
        "agent makes that the gates refuse. The uncatchable column is the honest limit — value errors no "
        "oracle-free property pins, where Veritas also ships (it flags soft, never false-greens).",
        "",
        "| Model | repeats | bare false-ship | Veritas false-ship | Veritas over-refusal | catchable false-ships (bare→Veritas) | reproducible |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(
            f"| {s.model} | {s.repeats} | {s.bare_false_ship:.0%} | {s.veritas_false_ship:.0%} | "
            f"{s.veritas_over_refusal:.0%} | {s.catchable_bare_false:.1f} → {s.catchable_veritas_false:.1f} | "
            f"{'yes' if s.reproducible else 'NO'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the trust benchmark.")
    ap.add_argument("--models", default="gemma-12b")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out", default="bench/TRUST_RESULTS.md")
    args = ap.parse_args()

    keys = [m.strip() for m in args.models.split(",") if m.strip() in MODELS]
    if not keys:
        print(f"no valid models; choose from {sorted(MODELS)}")
        return 1
    summaries = []
    for k in keys:
        print(f"running {k} x{args.repeats}…", flush=True)
        summaries.append(summarize(k, run_model(MODELS[k], args.repeats)))
    md = format_markdown(summaries)
    Path(args.out).write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
