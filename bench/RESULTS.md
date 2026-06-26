# Benchmark results — does the scaffold equalize models?

**Question:** does Veritas's deterministic scaffold let a cheap/fast model reach the same
*verified* bar as a slow reasoning model? Run the matrix and measure.

**Setup:** `bench/run_bench.py --repeats 3` · local Ollama · isolated memory per cell (no
cross-run learning, so this measures raw model+scaffold capability). Each cell is
`accepted-rate · mean wall-clock`. Run: 2026-06-19.

| goal | shape | qwen-9B | gemma-12B | llama-8B | qwen-64K (thinking) | sonnet (cloud) |
|---|---|---|---|---|---|---|
| double | function | **3/3** · 9s | **2/2** · 17s | **3/3** · 8s | **3/3** · 381s | **2/2** · 12s |
| reverse | function | 0/3 | 0/2 | **3/3** · 8s | **3/3** · 297s | 1/2 |
| clamp | function | **3/3** · 11s | 1/2 · 30s | **3/3** · 10s | **3/3** · 462s | **2/2** · 13s |
| temp | module | 0/3 | 1/2 · 33s | 0/3 | 1/3 · 493s | **2/2** · 15s |
| codec | module | 0/3 | 0/2 | 0/3 | 0/3 | **2/2** · 12s |

_(qwen-9B/llama/qwen-64K 3 repeats; gemma-12B & sonnet 2 repeats)_

**On model size (gemma-12B vs qwen-9B):** bigger was *not* clearly better. The 12B was flakier on
functions (`clamp` 1/2 vs the 9B's 3/3) — its failures trace to shakier oracle-free *properties*
(the same `reverse`/`clamp` property bug, model-independent), not capacity. At module scale it
nudged the ceiling (`temp` 1/2, matching the thinking model) but still couldn't clear `codec`
(0/2 — 0 for every local model). Takeaway: at this scale, proposal quality and cloud are the
levers, not parameter count.

## Findings

1. **At the achievable tier, the scaffold is the equalizer.** On `double`/`clamp`, the
   ~10s no-think model matches the ~40× slower thinking model — identical accepted-rate,
   same verified result. Cheap + gates = expensive reasoning, where the task is in reach.

2. **Thinking did not earn its keep here.** ~40× slower on every function, zero gain at the
   easy tier, and 1/3 + 0/3 on the modules (at 8–12 min/build). Not worth the latency.
   _(⚠ Revised — see the 2026-06-22 update below. This compared qwen-9B vs qwen-64K, which
   changed model size + context + thinking all at once. The clean same-model test tells a
   different story at module scale.)_

3. **The equalizer has a ceiling — and the gates hold it honestly.** At module scale nothing
   local clears reliably (codec 0/3 for *all three* models). The builds fail because the
   gates correctly reject work that doesn't compose (the round-trip integration test) — the
   system never manufactures capability the model lacks. **You never get a false green.** A
   too-weak model + Veritas yields *nothing*, loudly — not bad software.

4. **The gates are not the bottleneck — capability is.** `codec` was 0/3 for *all three* local
   models; Sonnet passes it 2/2 in 12s through the *same gates*. So the local failures were
   genuine capability limits and the gates are correctly calibrated — strict but not impossible.
   (Had Sonnet also gone 0/3, that would have meant the gates were broken. It didn't.) This
   turns the local-dev / cloud-product split from a guess into a measurement.

5. **A model-independent defect:** `reverse` tripped qwen-9B (0/3) *and* Sonnet (1/2) — not
   model weakness but a bad oracle-free property class (tagging the involution
   `reverse(reverse(x))==x` as `idempotent`). Worth fixing in the prompt for all models. Note
   too that even Sonnet uses the retry loop (`double` r2.0) — the scaffold helps the strong
   model, not only the weak ones.

## Takeaway

> The deterministic floor lets cheap models match expensive reasoning **wherever the task is
> achievable**, and honestly refuses — for *any* model — where it isn't. Reliability is never
> manufactured; the scaffold only guarantees you cannot get a false pass.

This empirically grounds the local-dev / cloud-product split: the local star handles functions
and iteration; module/app scale is where a stronger proposer (Sonnet) earns its place.

---

## Update (2026-06-22): the clean thinking A/B — and it flips the verdict

Finding #2 above ("thinking didn't earn its keep") rested on a **confounded** comparison:
qwen-9B (no-think) vs qwen-64K (think) is two *different* models — size, context window, and
the `think` flag all changed at once. So a clean test: **same model (gemma4:12b), only the
`think` flag differs**, on the two module goals, 2 repeats.

**Setup:** `bench/run_bench.py --shape module --repeats 2 --models gemma-12b,gemma-12b-think`

| goal | shape | gemma-12B (think **off**) | gemma-12B (think **on**) |
|---|---|---|---|
| temp | module | **0/2** · 35s · r2.0 | **2/2** · 140s · r0.0 |
| codec | module | **0/2** · 28s · r2.0 | **1/2** · 687s · r2.0 |

Plus a function smoke (think on): `double` 137s · `reverse` 108s · `clamp` **0/1** (458s, r2).

**What it shows (and it overturns finding #2 at module scale):**

1. **On gemma modules, thinking is the difference between shipping and not.** Think-off didn't
   reach the bar via retries — it exhausted them and shipped *nothing* (0/2 both). Think-on
   flipped `temp` to **2/2, first try, 0 retries**, and lifted `codec` 0 → 1/2. A genuine
   reject→accept flip, on the *same* model.

2. **On functions, thinking is strictly worse:** ~10× slower and it *failed* a `clamp` that
   think-off clears. So the cost is only worth paying where the shape is hard.

3. **Cost is real and variance is high:** think-modules ran 140–690s (vs ~30s off). `temp`
   2/2 is clean; `codec` is noisy — one clean 183s first-try win, one 1191s / 4-retry spiral
   that still failed. Thinking lifts gemma to the *edge* of module capability: clears the easy
   module reliably, makes the hard one occasionally possible instead of never.

4. **The scaffold kept it honest:** every think build that shipped cleared the *same* hard
   gates. `temp` 2/2 is verified work, not a thinking-induced false green.

**Shipped as policy:** `OllamaProvider.for_shape()` now turns thinking **on for module/app**
builds and leaves it **off for functions**; the software org's `build()` re-tunes the proposer
once the router has chosen the shape. Adaptive, not always-on — pay the thinking tax only where
it converts a failure into a verified ship.

**Open follow-up:** the `codec` 1191s/4-retry spiral argues for a retry cap (or time budget)
on the thinking path — it would bound worst-case latency on doomed builds without changing
accept-rate. Not yet implemented.

---

## Self-consistency as a confidence signal (2026-06-22) — measure-before-build

**Question:** could the research org drop the "you must provide sources" requirement and instead
answer from the model's own knowledge, *flagging* what's unreliable rather than refusing it? And is
**self-consistency** (does the model agree with itself across N samples?) a usable confidence flag?
We measured before building. `bench/selfconsistency.py` · gemma4:12b · 23 ground-truthed questions
spanning well-known / established / obscure / **recent (post-cutoff)** / false-premise traps · 8
samples each · temp 0.8.

**Findings (the design moved because of these):**

1. **Hedging beats raw self-consistency, decisively.** Given permission to say "I don't know," the
   model *consistently* admits ignorance rather than scattering — so on genuine unknowns (an obscure
   attendance figure, an obscure bassist) agreement stayed ~100% but **hedge rate hit 100%**. Raw
   agreement would call those "confident"; they're the opposite. Self-consistency (agreement) barely
   separated categories at N=8 (obscure 94% vs established 100%); the model's own *elicited* "I don't
   know" is the stronger, cheaper signal. The original self-consistency proposal is the weaker one.

2. **The recency disclaimer is NOT warranted — killed by data.** A blanket "don't trust post-2023
   facts" rule would have *falsely flagged four correct 2024 answers* (the US election, Euro 2024, the
   World Series, the Oscars — the model knew them all) and been redundant on the one it didn't know
   (Super Bowl LIX, Feb 2025), which it **correctly hedged**. The model self-discloses its real cutoff
   by hedging better than any fixed date rule could. Recency is *subsumed by hedge-detection*, not a
   separate mechanism.

3. **The irreducible blind spot, isolated and quantified: ~6%.** Exactly one confident-wrong slipped
   every signal — "how many studio albums had black midi released as of 2023?" → "2" at 88% agreement,
   no hedge (it's 3). Obscure, *pre*-cutoff, confidently wrong: not caught by hedging, scatter, or
   recency. 1/18 confident assertions ≈ 6% (small sample). This is the rate that bounds what a
   "confident" tier may ever claim — low enough to ship *labelled*, never low enough to call verified.
   (Low-agreement *did* catch the other wrong answers — Wet Leg at 75%, the Einstein trap at 88% — so
   layered signals flag everything unreliable *except* the ~6% confident-wrong.)

**Instrument honesty:** the first summary mislabelled two cases — it counted the *hedged* Super Bowl
answer as confident-wrong, and required a trap rejection to name the exact fact ("photoelectric") so it
scored a correct rejection as wrong. Both were measurement bugs (now fixed: a hedge isn't a confident
assertion; a trap is passed by correcting the premise any way). Corrected, both traps were handled
correctly and the confident-wrong rate is ~6%, not 11%.

**Design implication (data-backed):** build the knowledge mode on **elicited hedge-detection** as the
primary flag, low self-consistency as a secondary flag, recency folded in (not separate). Every claim
ships tagged model-asserted/confident or flagged — **never green**; the ~6% confident-wrong is disclosed,
not hidden. It's the inverse of grounding: ground only the flagged minority. (Design note:
`docs/confidence-layer.md`.) This run is exploration; the formal version is an Empirical Lab experiment
where the aggregate metric is stable enough to clear the reproducibility gate — the system gating its
own evolution.

### Promoted (2026-06-26): the bound is now a reproducible Empirical Lab experiment

The above is a *live* run — temp 0.8, it doesn't reproduce, so it cannot by itself govern a tier
(the reflexive rule: README §4.5 / ROADMAP principle 3). So it was promoted. The 8-sample run
(`results/selfconsistency_20260622-182254.md`) is frozen into a pinned transcript, and the
load-bearing number — the **confident-wrong rate** — is recomputed *deterministically* from that
frozen data in `bench/experiments/confidence_self_consistency.py`. The reproducibility is of the
*analysis*, not the sampling; that boundary is the honest part.

The claim, as a checkable hypothesis: among confidently-asserted answers (self-consistency ≥ 80% AND
no elicited hedge), the wrong rate is **< 10%**. Frozen result: **1/17 = 5.9%** confident-wrong. The
experiment is security-scanned, run 3× by a real subprocess executor, and clears the Empirical Lab's
`reproducibility` + `supports-hypothesis` gates — asserted in `tests/test_confidence_experiment.py`.
The confidence layer earned its place by passing the system it belongs to; the rate being **above
zero** is why the tier ships *labelled*, never *verified*.

---

## Can a PROMPT change move the verified bar? (2026-06-26) — the bootstrap prerequisite

**Question:** Veritas's own proposers run on system prompts (`SPEC_SYSTEM`, …). Before building a
"prompt studio" that tunes them, measure the prerequisite: does a prompt delta produce a *real,
reproducible* accept-rate signal through the unchanged gates — or just noise? `bench/promptbench.py`
A/Bs named variants of `SPEC_SYSTEM` across a goal set, with a cosmetic (neutral) control and a vague
(realistic-degradation) variant as guards. qwen-9b · **temp 0** (to isolate the prompt from sampling
noise) · 3×.

| variant | reverse | clamp | double | overall |
|---|---|---|---|---|
| baseline | 100% | 100% | 100% | **100%** |
| cosmetic (meaning-preserving reword) | 0% | 0% | 100% | **33%** |
| vague (drops schema + property guidance) | 0% | 0% | 0% | **0%** |

**Findings:**

1. **The signal is real and reproducible.** A realistic degradation took accept-rate 100% → 0% across
   every goal, stable at temp 0. Prompt quality moves the verified bar — the bootstrap prerequisite
   holds.

2. **There is no "cosmetic" edit to an LLM — and that is the finding.** A reword a human reads as
   identical (`"a precise software specification writer"` → `"a careful and precise author of software
   specifications"`) *deterministically* flipped `reverse` and `clamp` from pass to fail (0/3 each, at
   temp 0 — not sampling noise, a reproducible effect). Accept-rate tracks the prompt's exact tokens,
   not its human-perceived quality. An earlier temp-0.2 run blamed this on variance; temp 0 proved it
   real.

3. **This strengthens the case for the studio, it doesn't weaken it.** The standalone "prompt polish"
   tools judge a rewrite by *eyeballing* it. Finding #2 shows intuition is unreliable — the
   harmless-looking reword was a 67-point regression. So the only honest way to change a proposer
   prompt is to measure it against the gates (the reflexive rule, §4.5), which is exactly what a
   prompt studio is.

**Design constraints the data imposes (the spec for Slices 2–3):** measure at **temp 0** for a
reproducible verdict; use a **goal suite, never one goal** (`vague`'s drop was robust across all
goals, `cosmetic`'s was goal-specific — a single goal would mislead); **gate every candidate
empirically** — there are no safe edits to reason about. **Verdict: GO** — the formal version is an
Empirical Lab experiment (a prompt change ships only when its accept-rate gain reproduces on a
held-out goal suite), then the studio UI on top.
