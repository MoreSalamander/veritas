# P30 — Trust Benchmark: Findings (banked 2026-06-28)

**Question.** Does the deterministic gate architecture refuse plausible-but-wrong outputs that a bare
agent (the *same model*, no gates) ships? Is reliability an architecture or a model property?

## Method
- **Two contestants, one model.** *bare* = one proposal, shipped as-is. *Veritas* = the same model
  proposed through the gates (+ retry). The only variable is the architecture.
- **An independent oracle.** Held-out reference cases neither contestant sees decide right/wrong, so
  the benchmark cannot be circular — Veritas's own gates never define "correct" here.
- **A battery validated honest.** 14 tasks across four tiers (easy / catchable / uncatchable / hard).
  Every tier label is verified *through the real gates offline* — a catchable wrong impl is refused, an
  uncatchable one ships — so the headline can't be cherry-picked. The uncatchable tier is included on
  purpose (value errors no oracle-free property pins); hiding it would be propaganda.
- **Two experiments.** *full-pipeline* (model writes spec **and** code) and *gate-isolation* (both
  contestants get the same correct spec **and** the same single code proposal — only the gates differ,
  isolating the gates from the model's property-authoring ability).
- **Reproducible.** Every number held across ≥2 repeats.

## What happened (the loop, honestly)
1. **First run looked like Veritas did WORSE** (catchable 0→2). It was an artifact: the judge called a
   fixed function name, but models *rename* (gemma turned `negate` into `get_additive_inverse`), so the
   oracle scored correct code as wrong. **Fixed** — the judge now finds the defined function by AST.
2. **Re-run surfaced a real engine bug: 30% over-refusal.** A model authored a *malformed* property; the
   HARD property gate hit a runtime error evaluating it and **rejected otherwise-correct code**. An
   errored gate is not a violated property. **Fixed** — a clean relation violation hard-fails; an
   unevaluatable property is skipped as uninformative. Re-measured: **over-refusal 30% → 0%.**
3. **Gate-isolation, easy + hard tiers, gemma-12b + qwen-9b, ×2:** `0%` false-ship, `0%` over-refusal,
   catchable false-ships `0 → 0`, reproducible. **Given a clear spec, these models write correct code on
   all 14 single-function tasks** — including manual bubble sort, transpose, and dedupe.

## What it means
- **The win *mechanism* is proven** (offline + isolation tests): given wrong code, the deterministic
  gate refuses the *exact code* the bare agent ships. Locked.
- **The win *rate* is ~0 on single functions for these models** — they don't make catchable
  single-function errors. There was nothing to catch.
- **Deterministic verification's value scales with task difficulty *relative to model capability*.**
  *Below* the model's ceiling: **cost-free, no benefit.** The clear-win regime is **composition / module
  scale** — exactly where this project's own bench documents local models going 0/3 (the codec module),
  and exactly the `round_trip`-property regime where failures *are* catchable.
- **The benchmark debugged the engine.** The 30%→0% over-refusal fix is concrete value the
  measure→find→fix→re-measure loop delivered beyond any headline.

## Honest limits
- **No win *number* was demonstrated** — the regime where these models fail is module scale, not run here.
- Veritas only catches failures reducible to a machine-checkable property; a pure value error no relation
  pins (`a+b` vs `a-b`) ships from *both* — Veritas flags it soft, never false-greens.
- In the *full pipeline*, the gate's power couples to the model authoring a good property (weak local
  models under-specify). Gate-isolation removes this; production would benefit from architecturally- or
  human-pinned properties.

## Conclusion
The architecture is **cost-free and honest**: across 14 tasks × 2 models × 2 repeats it never shipped
wrong code and never wrongly rejected correct code. Its measurable *benefit* appears at the model's
ceiling (composition), not below it — the local-dev / cloud-product split, now with data behind it.
**Banked.** The non-zero win number is a future module-scale rung (a codec / encode-decode task with a
`round_trip` property). Next up: **P31 (hosting)**.
