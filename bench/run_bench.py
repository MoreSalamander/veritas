#!/usr/bin/env python
"""Veritas benchmark — does the deterministic scaffold let a cheaper/faster model reach the
same VERIFIED bar as a slower reasoning model?

Runs a matrix of goals x models, each build isolated in its own memory (no cross-run learning,
so we measure raw model+scaffold capability), and records what actually matters:

    accepted    — did it clear every HARD gate (the only definition of "done" that counts)
    retries     — how many times the org had to self-correct to get there
    time        — wall-clock seconds (the real cost on local hardware)

The headline question, in numbers: for the same goal, does qwen-9b (no-think) reach the same
accepted=True as qwen-64k (thinking), and at what ratio of time/retries? Turns the N=1 we saw
into a table you can quote.

Usage:
    .venv/bin/python bench/run_bench.py                      # default matrix
    .venv/bin/python bench/run_bench.py --repeats 3          # 3x each cell (variance)
    .venv/bin/python bench/run_bench.py --models qwen-9b,llama-8b   # subset
    .venv/bin/python bench/run_bench.py --quick              # functions only (fast)
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

import os  # noqa: E402

# load the gitignored .env so the cloud models have their API key
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from engine.memory import MemoryStore  # noqa: E402
from engine.model import ClaudeProvider, OllamaProvider  # noqa: E402
from orgs.software_studio.builder import build  # noqa: E402

# model_key -> factory. Each cell builds a fresh provider (clean state).
MODELS = {
    "qwen-9b": lambda: OllamaProvider(model="qwen3.5:9b", think=False, timeout=300),
    "gemma-12b": lambda: OllamaProvider(model="gemma4:12b", think=False, timeout=300),
    # Clean think-on vs think-off A/B: SAME model (gemma4:12b), only the `think` flag differs —
    # unlike the qwen 9b-vs-64k comparison, which confounded model size + context + thinking.
    "gemma-12b-think": lambda: OllamaProvider(model="gemma4:12b", think=True, timeout=900),
    "llama-8b": lambda: OllamaProvider(model="llama3.1:8b", think=False, timeout=300),
    "qwen-64k-think": lambda: OllamaProvider(model="qwen3.5-64k:latest", think=True, timeout=900),
    "sonnet": lambda: ClaudeProvider(model="claude-sonnet-4-6"),  # cloud — costs a few cents/build
}

# (label, goal, forced shape) — shape is forced so every model builds the SAME thing (fair).
GOALS = [
    ("double", "a function that doubles a number", "function"),
    ("reverse", "a function that reverses a string", "function"),
    ("clamp", "a function that clamps a number to be at least zero", "function"),
    ("temp", "a temperature converter module with celsius_to_fahrenheit and fahrenheit_to_celsius", "module"),
    ("codec", "a module that encodes a number by adding 100 and decodes by subtracting 100", "module"),
]


def run_one(factory, goal: str, shape: str) -> dict:
    provider = factory()
    mem = MemoryStore(pathlib.Path(tempfile.mkdtemp()))
    t0 = time.perf_counter()
    try:
        res = build(goal, provider, mem, shape=shape)
        dt = time.perf_counter() - t0
        retries = len([e for e in res.activity if e.actor == "retry"])
        return {"accepted": res.accepted, "retries": retries, "time": dt, "error": None}
    except Exception as exc:
        return {"accepted": False, "retries": 0, "time": time.perf_counter() - t0,
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--quick", action="store_true", help="functions only")
    ap.add_argument("--shape", default="", help="only goals of this shape (function|module)")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip() in MODELS]
    goals = [g for g in GOALS if not (args.quick and g[2] != "function")]
    if args.shape:
        goals = [g for g in goals if g[2] == args.shape]
    rows: list[dict] = []

    print(f"matrix: {len(goals)} goals x {len(models)} models x {args.repeats} repeat(s)\n", flush=True)
    for label, goal, shape in goals:
        for mkey in models:
            for r in range(args.repeats):
                res = run_one(MODELS[mkey], goal, shape)
                res.update({"goal": label, "shape": shape, "model": mkey})
                rows.append(res)
                mark = "OK " if res["accepted"] else "XX "
                extra = f" err={res['error']}" if res["error"] else ""
                print(f"  {mark}{label:8} {shape:8} {mkey:16} "
                      f"{res['time']:6.0f}s retries={res['retries']}{extra}", flush=True)

    # aggregate per (goal, model)
    def agg(goal: str, model: str) -> dict:
        cells = [x for x in rows if x["goal"] == goal and x["model"] == model]
        acc = [x for x in cells if x["accepted"]]
        return {
            "rate": f"{len(acc)}/{len(cells)}",
            "time": statistics.mean(x["time"] for x in cells) if cells else 0.0,
            "retries": statistics.mean(x["retries"] for x in cells) if cells else 0.0,
        }

    lines = ["# Veritas benchmark", "",
             f"_{datetime.now(timezone.utc).isoformat()} · {args.repeats} repeat(s) per cell_", "",
             "| goal | shape | " + " | ".join(models) + " |",
             "|---|---|" + "---|" * len(models)]
    for label, _goal, shape in goals:
        cells = []
        for mkey in models:
            a = agg(label, mkey)
            cells.append(f"{a['rate']} · {a['time']:.0f}s · r{a['retries']:.1f}")
        lines.append(f"| {label} | {shape} | " + " | ".join(cells) + " |")
    lines += ["", "_cell = accepted-rate · mean wall-clock · mean retries_"]
    table = "\n".join(lines)

    out = ROOT / "bench" / "results" / f"bench_{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    out.write_text(table + "\n")
    print("\n" + table)
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
