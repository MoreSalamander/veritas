# Knowledge Mode + the Confidence Layer — a design note

_Status: designed, not built. The design rests on a recorded measurement
(`bench/RESULTS.md` → "Self-consistency as a confidence signal", 2026-06-22)._

## The problem

The Research Studio verifies by **grounding**: every claim must trace, verbatim, to a source in a
**corpus you provide**. That's honest and strong — but it means the org isn't really a *researcher*.
It's a grounded **writer**. As the user put it: *"if I feed in the info, I already did the research."*
A real researcher **finds** what it needs; ours makes you find it first.

We want a mode where you ask a question and the system answers from the **model's own knowledge** —
without you supplying sources — while being **honest about what to trust**. The danger is obvious and
it's the whole reason Veritas exists: a model answering from memory will sometimes be confidently
wrong, and we must never launder that into a verified-looking answer.

## What the measurement settled (so we don't design on intuition)

We measured before building. The data moved the design in three ways:

1. **Hedge-detection beats self-consistency.** Given permission to say "I don't know," the model
   *consistently admits ignorance* rather than scattering — so raw agreement barely discriminates
   (obscure 94% vs established 100%), but the model's **elicited "I don't know"** cleanly flags the
   unknowns. The primary signal is hedging, not N-sample voting.
2. **No recency disclaimer.** A blanket "don't trust post-2023 facts" rule would have *falsely flagged
   four correct 2024 answers* and been redundant on the one the model didn't know (which it hedged).
   The model self-discloses its real cutoff by hedging. Recency is **subsumed**, not separate.
3. **An irreducible blind spot, ~6%.** Exactly one confident-wrong slipped every signal (an obscure,
   *pre*-cutoff album count: "2" at 88% agreement, no hedge — it's 3). No self-report catches it. This
   is the rate that bounds what a "confident" answer may ever claim.

## The design

### It is a MODE, not a new org

A new org needs a **machine-proven floor** (≥1 HARD gate that checks against the world). This has none —
its strongest honest claim is "the model asserts this, and didn't flag uncertainty," which proves
nothing about truth. Standing it up as a peer org (same nav, same "Studio" frame) would imply
verification weight it doesn't have. So it's a **mode of the Research Studio** — "ask without sources" —
and a reusable **confidence layer**, honestly soft. (The deeper doctrine rule — *never show something as
more verified than it is* — outranks the surface rule that a different method means a different org.)

### The signals (layered, cheap → costly)

| signal | what it catches | strength |
|---|---|---|
| **elicited hedge** (primary) | the model *admits* it doesn't know | the model's own uncertainty, when invited — the cleanest cheap signal |
| **low self-consistency** (secondary) | wrong-but-unhedged answers that *wobble* across samples (caught Wet Leg @75%) | complement; weak alone, useful in combination |
| ~~recency rule~~ | — | dropped; subsumed by hedging |

Together they flag everything unreliable **except** the ~6% confident-wrong. That residual is the
honest cost of the mode.

### The trust tier — and the one invariant

Every claim is tagged, and lives in the **model-judged (soft)** tier — never machine-proven:

- **confident** — high agreement, no hedge → ships labelled *"model-asserted · unverified"*.
- **flagged** — hedged or low-agreement → surfaced for the human, or handed to grounding.

**Invariant (inviolable):** a confident-consensus claim is **never** rendered as verified/green, and the
mode **discloses its ~6% confident-wrong rate** in the UI. The day "the model was sure" is shown as
"true" is the day a Veritas green stops meaning anything.

### How it composes — the inverse of grounding

This isn't a replacement for the grounding org; it's its **triage front-end**. The model drafts from
knowledge; the flags become the **worklist** of what actually needs sourcing. You ground the flagged
*minority* instead of providing sources for *everything* — which is exactly the user's original ask.

```
question
   │
   ▼
draft from knowledge ──► per-claim confidence (hedge + self-consistency)
   │                          │
   │                 ┌────────┴─────────┐
   ▼                 ▼                  ▼
confident         flagged            flagged
"model-asserted   → human verify     → hand to Research (ground it)
 · unverified"
```

## What to build first (the slice)

1. A `confidence` module: `elicit_answer` (asks with "say I don't know if unsure"), `is_hedge`,
   and an N-sample `self_consistency` measure → a per-claim `Confidence{level, agreement, hedged}`.
2. A Research **mode** (`build_brief` or similar): question → multi-claim draft → per-claim confidence
   → a report where each claim carries its tag; flagged claims listed as the grounding worklist.
3. A **soft** `ConfidenceGate` that annotates (never blocks) and the UI tier that shows
   confident/flagged honestly + the disclosed confident-wrong rate. No HARD gate here — by design.

## Open / later

- **Formalize as an Empirical Lab experiment.** This run was exploration (a script). The trustworthy
  version makes the aggregate metric stable enough to clear the **reproducibility gate** — at which
  point the result is a *verified* finding, not a hand-read one.
- **Re-measure across models** (the ~6% is gemma4:12b, N=8, hand-picked questions — qualitative
  findings are solid, the exact rate is rough). Different models will have different confident-wrong
  rates; the tier's honesty depends on measuring each.
- **Hedge-elicitation could itself be gamed** by prompt phrasing; worth testing robustness.

## The meta note

This design was chosen by **Veritas's own method**: an empirical measurement killed two plausible
features (raw self-consistency as primary; a recency disclaimer) and surfaced a better one. The system
gated its own evolution — the reproducibility/measurement discipline applied to what Veritas should
*become*, not just to what it builds. That principle — *no new verification mechanism is trusted until
it passes the system's own empirical bar* — is worth making explicit as project governance.
