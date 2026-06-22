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
