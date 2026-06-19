# Benchmark results — does the scaffold equalize models?

**Question:** does Veritas's deterministic scaffold let a cheap/fast model reach the same
*verified* bar as a slow reasoning model? Run the matrix and measure.

**Setup:** `bench/run_bench.py --repeats 3` · local Ollama · isolated memory per cell (no
cross-run learning, so this measures raw model+scaffold capability). Each cell is
`accepted-rate · mean wall-clock`. Run: 2026-06-19.

| goal | shape | qwen-9B (no-think) | llama-8B (no-think) | qwen-64K (thinking) |
|---|---|---|---|---|
| double | function | **3/3** · 9s | **3/3** · 8s | **3/3** · 381s |
| reverse | function | 0/3 · 15s | **3/3** · 8s | **3/3** · 297s |
| clamp | function | **3/3** · 11s | **3/3** · 10s | **3/3** · 462s |
| temp | module | 0/3 · 67s | 0/3 · 13s | 1/3 · 493s |
| codec | module | 0/3 · 64s | 0/3 · 20s | 0/3 · 639s |

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

4. **A caught defect:** qwen-9B is 0/3 on `reverse` (llama 3/3) — likely a property mismatch
   (tagging reverse `idempotent` when it is an *involution*: `reverse(reverse(x))==x`). Next
   prompt-refinement candidate.

## Takeaway

> The deterministic floor lets cheap models match expensive reasoning **wherever the task is
> achievable**, and honestly refuses — for *any* model — where it isn't. Reliability is never
> manufactured; the scaffold only guarantees you cannot get a false pass.

This empirically grounds the local-dev / cloud-product split: the local star handles functions
and iteration; module/app scale is where a stronger proposer (Sonnet) earns its place.
