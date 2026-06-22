#!/usr/bin/env python
"""Does self-consistency predict factual reliability? — the (tightened) exploratory measurement.

The proposal: let the model answer from its own knowledge, and use SELF-CONSISTENCY (does it give
the same answer across N independent samples?) as a soft confidence flag — low agreement = flag for
a human or for grounding. This tests whether that signal actually discriminates, BEFORE we build on it.

Tightened over v1:
  * EVERY question is ground-truthed (string match, or "UNKNOWABLE") -> the CONFIDENT-WRONG rate is
    counted automatically. That rate is the number that decides whether a "confident" tier is safe.
  * a RECENT category (clearly post-training-cutoff facts) probes whether self-consistency catches
    recency on its own, or whether a separate "don't trust post-cutoff facts" disclaimer is needed.
  * HEDGE detection — the model's own "I don't know" language, which v1 hinted beats raw agreement.
  * trap verdicts judged against the truth (a false premise is "passed" only if the model CORRECTS it).

Per question:  agreement = fraction of N samples matching the modal answer.  hedged = any sample
self-reports uncertainty.  Run:  .venv/bin/python bench/selfconsistency.py [--samples N]
"""

from __future__ import annotations

import argparse
import pathlib
import re
import statistics
import sys
from collections import Counter
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.model import OllamaProvider  # noqa: E402

MODEL = "gemma4:12b"
HIGH = 0.8  # agreement at/above this = "confident"

# (category, question, truth)  — truth is a lowercase substring expected in a correct answer,
# "UNKNOWABLE" for genuinely-unanswerable (correctness undefined; we want scatter/hedge here),
# or "REJECT:<word>" for a false-premise trap (correct iff the answer contains <word>).
QUESTIONS: list[tuple[str, str, str]] = [
    # well-known — should be consistent AND correct
    ("well-known", "What is the chemical symbol for gold?", "au"),
    ("well-known", "What planet is known as the Red Planet?", "mars"),
    ("well-known", "How many legs does an insect have?", "6"),
    ("well-known", "What is the capital of Japan?", "tokyo"),
    ("well-known", "At what temperature in Celsius does water boil at sea level?", "100"),
    # established — specific but well-documented older facts
    ("established", "In what year did the first Apollo Moon landing happen?", "1969"),
    ("established", "Who wrote the play Romeo and Juliet?", "shakespeare"),
    ("established", "In what year did the Titanic sink?", "1912"),
    ("established", "In what year did the Berlin Wall fall?", "1989"),
    ("established", "Who painted the Mona Lisa?", "leonardo"),
    # obscure — now ground-truthed, so confident-wrong is counted (black midi was the v1 blind spot)
    ("obscure", "What city was the rapper Ice Spice born in?", "new york"),     # the Bronx, NYC
    ("obscure", "In what year was the video game Hollow Knight first released?", "2017"),
    ("obscure", "What was the debut single of the band Wet Leg?", "chaise longue"),
    ("obscure", "How many studio albums had the band black midi released as of 2023?", "3"),  # v1: said 2
    ("obscure", "What was the total attendance at the 2014 Latvian second-division football final?", "UNKNOWABLE"),
    ("obscure", "What is the middle name of the bassist of the band Geese?", "UNKNOWABLE"),
    # recent — clearly post-cutoff; does the model scatter (good) or confidently confabulate (needs the recency disclaimer)?
    ("recent", "Who won the 2024 United States presidential election?", "trump"),
    ("recent", "Which country won the UEFA Euro 2024 football tournament?", "spain"),
    ("recent", "Which team won the 2024 World Series in baseball?", "dodgers"),
    ("recent", "Who won Super Bowl LIX, played in February 2025?", "eagles"),
    ("recent", "What film won the Academy Award for Best Picture at the March 2024 ceremony?", "oppenheimer"),
    # traps — a FALSE premise; correct = the model CORRECTS it
    ("trap", "In what year did Albert Einstein win the Nobel Prize for his theory of relativity?", "REJECT:photoelectric"),
    ("trap", "In what year did Leonardo da Vinci paint the Sistine Chapel ceiling?", "REJECT:michelangelo"),
]

_SYSTEM = ("Answer with ONLY the fact, in as few words as possible. No explanation. "
           "If you do not know, say 'I don't know'.")
_HEDGES = ("dont know", "do not know", "not available", "unknown", "cannot", "unable",
           "not sure", "unclear", "no data", "not enough", "no middle name", "not provide", "never")


def normalize(s: str) -> str:
    s = s.strip().lower().splitlines()[0] if s.strip() else ""
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\b(the|a|an|in|of|is|was|year|won|by)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def is_hedge(s: str) -> bool:
    return any(h in s for h in _HEDGES)


# generic "the model pushed back on the premise" markers — a trap is passed by correcting it ANY way,
# not only by naming the specific fact (v1 required the exact word and mislabelled a correct rejection).
_REJECTION = ("did not", "didnt", "never", "actually", "incorrect", "not win", "no ", "wrong")


def judge(top: str, samples: list[str], truth: str) -> bool | None:
    if truth == "UNKNOWABLE":
        return None
    if truth.startswith("REJECT:"):
        word = truth.split(":", 1)[1]
        return any(word in s or any(r in s for r in _REJECTION) for s in samples)  # corrected the premise
    return truth in top or top in truth


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=8)
    args = ap.parse_args()
    n = args.samples
    provider = OllamaProvider(model=MODEL, temperature=0.8, think=False, timeout=120)

    print(f"self-consistency on {MODEL} · {len(QUESTIONS)} questions x {n} samples (temp 0.8)\n", flush=True)
    rows: list[dict] = []
    for cat, q, truth in QUESTIONS:
        samples = [normalize(provider.propose(role="fact", prompt=q, system=_SYSTEM)) for _ in range(n)]
        counts = Counter(s for s in samples if s)
        top, topn = (counts.most_common(1)[0] if counts else ("", 0))
        agreement = topn / n
        hedge_rate = sum(1 for s in samples if is_hedge(s)) / n
        correct = judge(top, samples, truth)
        rows.append({"cat": cat, "q": q, "agreement": agreement, "distinct": len(counts),
                     "top": top, "correct": correct, "hedge": hedge_rate, "truth": truth})
        mark = {True: "✓", False: "✗", None: "·"}[correct]
        print(f"  [{cat:11}] agree={agreement:.0%} hedge={hedge_rate:.0%} {mark} "
              f"top={top!r:26.26} :: {q[:46]}", flush=True)

    print("\n--- H1: does agreement separate the familiar from the obscure/recent? ---")
    for cat in ("well-known", "established", "obscure", "recent", "trap"):
        ags = [r["agreement"] for r in rows if r["cat"] == cat]
        if ags:
            print(f"  {cat:11} mean agreement {statistics.mean(ags):.0%}  (n={len(ags)})")

    # H2 — the decision number: of the CONFIDENT answers, how many are WRONG? (the blind spot rate)
    judged = [r for r in rows if r["correct"] is not None and not r["truth"].startswith("REJECT:")]
    # "confident" = high agreement on an actual ASSERTION — a hedged "I don't know" is not a confident
    # claim, so it must not count as confident-wrong (v1 miscounted the hedged Super Bowl answer).
    confident = [r for r in judged if r["agreement"] >= HIGH and not is_hedge(r["top"])]
    conf_wrong = [r for r in confident if r["correct"] is False]
    print(f"\n--- H2: the blind spot — confident answers that are WRONG (self-consistency can't catch) ---")
    print(f"  confident (agree>={HIGH:.0%}) AND wrong: {len(conf_wrong)} / {len(confident)} confident answers "
          f"= {len(conf_wrong)/len(confident):.0%} confident-wrong rate" if confident else "  (no confident answers)")
    for r in conf_wrong:
        print(f"    WRONG@{r['agreement']:.0%}  said {r['top']!r} (truth ~{r['truth']!r})  :: {r['q']}")

    print("\n--- recency: did post-cutoff facts get caught by scatter/hedge, or confidently confabulated? ---")
    for r in [r for r in rows if r["cat"] == "recent"]:
        caught = r["agreement"] < HIGH or r["hedge"] >= 0.5
        verdict = ("flagged (scatter/hedge)" if caught else
                   ("confident+CORRECT" if r["correct"] else "CONFIDENT+WRONG -> needs recency disclaimer"))
        print(f"  agree={r['agreement']:.0%} hedge={r['hedge']:.0%} correct={r['correct']} -> {verdict}  :: {r['q'][:40]}")

    print("\n--- traps (false premise) ---")
    for r in [r for r in rows if r["cat"] == "trap"]:
        print(f"  {'CORRECTED' if r['correct'] else 'TOOK THE FALSE PREMISE'} (agree={r['agreement']:.0%})  said {r['top']!r}")

    out = ROOT / "bench" / "results" / f"selfconsistency_{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Self-consistency measurement (tightened)", "",
             f"_{datetime.now().isoformat()} · {MODEL} · {n} samples/question · temp 0.8_", "",
             "| category | question | agreement | hedge | correct |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['cat']} | {r['q']} | {r['agreement']:.0%} | {r['hedge']:.0%} | "
                     f"{ {True:'yes',False:'NO',None:'—'}[r['correct']] } |")
    out.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
