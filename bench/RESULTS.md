# Benchmark results — does the scaffold equalize models?

**Question:** does Veritas's deterministic scaffold let a cheap/fast model reach the same
*verified* bar as a slow reasoning model? Run the matrix and measure.

**Setup:** `bench/run_bench.py --repeats 3` · local Ollama · isolated memory per cell (no
cross-run learning, so this measures raw model+scaffold capability). Each cell is
`accepted-rate · mean wall-clock`. Run: 2026-06-19.

| goal | shape | qwen-9B (no-think) | llama-8B (no-think) | qwen-64K (thinking) | sonnet (cloud) |
|---|---|---|---|---|---|
| double | function | **3/3** · 9s | **3/3** · 8s | **3/3** · 381s | **2/2** · 12s |
| reverse | function | 0/3 · 15s | **3/3** · 8s | **3/3** · 297s | 1/2 · 16s |
| clamp | function | **3/3** · 11s | **3/3** · 10s | **3/3** · 462s | **2/2** · 13s |
| temp | module | 0/3 · 67s | 0/3 · 13s | 1/3 · 493s | **2/2** · 15s |
| codec | module | 0/3 · 64s | 0/3 · 20s | 0/3 · 639s | **2/2** · 12s |

_(local cells 3 repeats; sonnet 2 repeats)_

## Findings

1. **At the achievable tier, the scaffold is the equalizer.** On `double`/`clamp`, the
   ~10s no-think model matches the ~40× slower thinking model — identical accepted-rate,
   same verified result. Cheap + gates = expensive reasoning, where the task is in reach.

2. **Thinking did not earn its keep here.** ~40× slower on every function, zero gain at the
   easy tier, and 1/3 + 0/3 on the modules (at 8–12 min/build). Not worth the latency.

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
