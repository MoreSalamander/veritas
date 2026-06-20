# Veritas Dynamics — Roadmap

Companion to [README.md](README.md) (the founding doc). The README is *what & why*.
This is *in what order, and how we know each phase is real.*

---

## Two principles that shape the whole sequence

**1. Build the org first; extract the hub from it.**
The instinct is to build the central hub first — it's the platform, it's what the
preview leads with (Mission Control). We won't. You cannot design the hub well until you
know what an organization actually *needs* from it, and the only way to learn that is to
run one real org against bare metal. So: build the minimum substrate → run one real org
on it → let that org teach us what the hub must provide → *then* generalize the hub. This
is the Veritas meta-thesis applied to Veritas itself (the software org teaches us how
orgs should work), and it's how every MoreSalamander tool has actually shipped — offline
scaffold + tests first, UI last.

**2. "Done" means a gate earned it — including a real rejection.**
No phase is complete on a green screenshot. Each phase's definition-of-done requires a
deterministic check passing **and**, from Phase 1 on, a real artifact being *rejected*
into failure memory. The green has to be earned by a gate that is capable of saying no.

---

## One open decision (everything else is settled)

**Engine stack.** Recommendation: **Python** for the substrate + software org, reusing
the proven MoreSalamander pattern — local Ollama models behind a `model_router` with
**judge-separation** (the verifying model is never the proposing model, exactly as in
myAIstro), deterministic gates via `pytest` / `mypy` / schema validation. The hub UI
later reuses the **AgentForge React shape**. Rationale: 100% of the shipped suite is
Python + local models, the gates we depend on are Python-native, and the thesis itself
(judge-separation, scorer-as-gate) is already implemented in your code. The Replit
preview's TypeScript was throwaway visual shape, not a stack commitment.
*Veto-able — say the word if you want TS end-to-end instead.*

### Model boundary & shipping (decided early, even though cloud comes later)

**This ships. It is not a local personal tool — it only looks like one for a while.**
Dev/test runs on **local LLMs** (Ollama); the **product runs on cloud API.** The thesis
makes this nearly free: because reliability lives in the *deterministic gates*, not the
model, **the model is swappable by design** — a gate doesn't care which model proposed an
artifact, it just checks it. So from the *first* model call (Phase 1) we put every model
behind a provider-agnostic interface (`propose(role, prompt) -> text`), with local Ollama
and cloud API as interchangeable backends selected by config. Local→cloud becomes a
backend swap, never a rewrite.

Deep cloud conversation happens at two points: **Phase 1** (when the model boundary first
appears — confirm the interface) and **Phase 4** (when shipping gets concrete — provider
choice, auth, cost ceilings, *where the deterministic gates run in production*, and
multi-tenancy). Until then we build local, ship-ready.

---

## Repo shape (single repo, `~/MoreSalamander/veritas`)

```
veritas/
  engine/          # the substrate / OS — Artifact, Gate, Memory, Run (state machine)
  orgs/
    software_studio/   # the first org: the cast (agents) + its gates
  hub/             # control plane: registry, Mission Control API + UI  (Phase 4+)
  memory/          # institutional memory store (file-per-record + index)
  tests/
```

---

## The phases

### Phase 0 — The Spine  *(engine, offline, no LLM)* ✅
The data model and the loop, before a single agent exists.
- **Build:** `Artifact` (typed, owned, status, full provenance) · `Gate`
  (interface declaring **hard|soft**, returns pass/fail + evidence) · `Memory` store
  (reuse myAIstro's file-per-record + frontmatter + index) · `Run` — the state machine
  that walks an artifact through Explain → Synthesize → Verify → Persist · the failure
  record.
- **Done when:** `pytest` green; a hand-built artifact pushed through a *stub passing*
  gate persists with a complete provenance trail, and through a *stub failing* gate lands
  in failure memory. Proposers are stubs. The loop is real even though nothing is smart yet.

### Phase 1 — One Honest Run  *(software_studio, minimal cast)* ✅
The thesis, proven in the smallest unit that can prove it.
- **Build:** one narrow capability (e.g. "goal → one REST endpoint"). A **Spec** agent
  (one local proposer) → Spec artifact gated by a **spec-scorer** that *rejects any spec
  whose acceptance criteria aren't executable*. A **Developer** agent → code artifact
  gated by `pytest` + `mypy` + the generated acceptance-tests. Judge-separation anywhere a
  model judges.
- **Done when:** one run produces a genuinely gate-validated artifact in memory **and** a
  second run (bad spec or failing code) produces a real rejection in failure memory. The
  green is earned. This is the homerun swing in miniature.

### Phase 2 — The Cast  *(software_studio fills out)* ✅
The full organization from the preview, made real.
- **Build:** Architect, QA, Security, Validation as additional proposers, each emitting a
  typed artifact (API-CONTRACT / PLAN / TEST / SECURITY-REPORT) behind its own gate.
  Full Explain→Synthesize→Verify→Persist with the real roster. Validation agent is the
  final gate before persist. Every persisted artifact carries a complete provenance trail
  (who made it / why / what validated it / why accepted).
- **Done when:** the e-commerce-style run from the preview happens *for real*, end to end,
  with at least one gate capable of halting or triggering a retry, and no artifact reaches
  memory without complete provenance.

### Phase 3 — The Org Learns  *(institutional memory goes active)* ✅
Where "the system that learns how to build the system" stops being a slogan.
- **Build:** failure + lesson **retrieval** — when a new task starts, surface relevant
  past failures/lessons (tag or embedding match over institutional memory) into the
  proposer's context; the retry loop is informed by what was retrieved.
- **Done when:** a measurable drop in repeat failures across runs, and a run *visibly
  avoids* a mistake a prior run made — with the retrieved memory recorded in its
  provenance.

### Phase 4 — The Hub  *(control plane, extracted from what the org proved it needs)* ✅
Now the central hub the organizations live in.
- **Build:** org **registry** (an org = substrate + a cast manifest; stand one up from
  config) · **Mission Control** API + dashboard fed by *real* telemetry · cross-org shared
  memory + governance · multi-project. Wire the AgentForge UI shape to the real engine.
- **Done when:** you start a run from the hub UI, watch real (not scripted) telemetry,
  and browse real institutional memory — all backed by the engine, nothing mocked.

### Phase 5 — Second Org Type  *(prove the reusability claim)* ⏳ *(next — see P14)*
The meta-thesis validated.
- **Build:** stand up a second org (e.g. a Research Lab, or a Production Studio echoing
  scene/beats) on the **unchanged** substrate by swapping only the cast + its gates.
- **Done when:** a non-software org runs on the same engine, proving "only the agents
  change."

---

## Where the two things you named live

- **The central hub for the organizations to live** → Phase 4 (its *concept* leads from
  day one; its *code* is extracted once Phase 0–3 reveal what it must hold).
- **The software organization** → Phases 1–3 (the first, and the proving ground for
  everything else).

First brick: **Phase 0 — the spine**, and inside it, the first honest thing to exist is
the gate that is capable of rejecting.

---

## The 10-month arc (Jun 2026 → Apr 2027)

**Status (Jun 2026):** P0–P12 are done — the full build chunk landed ahead of the arc.
The engine substrate, the software org with its complete cast, institutional memory
(failures *and* decisions), the retry loop, the hub + registry, the cloud model provider,
and a 3-way model toggle (local / Haiku / Sonnet / Opus) are all built and tested. The
north star of this chunk is **met**: a natural-language goal now walks autonomously through
*plan → modules → assembled package → entrypoint → end-to-end-verified runnable app* — and
a representative build came back **accepted green, zero retries, on a frontier model.** The
cast earned their seats one verifiable artifact at a time; nothing was added before there
was something for it to check.

### The build chunk — done (fine rungs; numbers climb monotonically forever)

Each rung added one verifiable thing behind one gate.

- **P6 · Module** ✅ — function → module; Architect + PM gated; integration gate guards composition.
- **P7 · Unify + wire** ✅ — one `build(goal)` routes function vs module; hub rides on it.
- **P8 · Planner** ✅ — a goal too big for one module → a *plan* (list of module contracts).
  Planner seat; `PlanGate`. Validated multi-module plan, no code.
- **P9 · Assembly** ✅ — build each planned module; prove they coexist (importable together,
  no name clashes). `AssemblyGate`. Plan → assembled package.
- **P10 · Entrypoint + E2E** ✅ — app = modules + entrypoint + end-to-end test. Integrator
  seat; `EntrypointGate` + `E2EGate`. Goal → runnable small app, e2e green. The
  entrypoint↔e2e *handshake* fix (PM authors the e2e first, as `main()`'s contract;
  Integrator implements against it; retry re-checks against the same tests) is what carried
  a whole app to green on a frontier model.
- **P11 · Memory seat** ✅ — decision records persisted and surfaced on related builds; a
  build's decisions now inform a later related build (`MemoryRecord.from_decision`).
- **P12 · Retry loop** ✅ — on rejection, re-propose with gate feedback within the run
  (`run.attempt` + scoring). Fail → feedback → succeed, in one run. Autonomy began here.

### What's next (the remaining arc, Jul 2026 → Apr 2027)

The build chunk proved the thesis *works*; the next rungs make it **robust** and **plural**.

- **P13 · Structured oracles** (Jul–Sep) — take raw LLM-authored value assertions out of the
  HARD gates entirely. Hard gates verify only against structured/metamorphic specs
  (round-trips, invariants, fixed points, type/contract checks) — never a number the model
  wrote. *Done: no app hard gate trusts a model-written oracle; app builds move from
  occasionally-lucky to reliably-green.* This is the deepest robustness play. Sub-rungs:
  - **P13a · Property vocabulary** ✅ — closed oracle-free relation kinds (round_trip,
    idempotent, monotonic, invariant) + injection-safe harness; 15 tests bite mutants.
  - **P13b · PropertyGate hard / cases soft** ✅ — oracle-free `PropertyGate` is the HARD
    behavioral authority; exact `expected` cases demoted to SOFT (model-authored oracle =
    advisory). The honest limit (no relation pins `a+b` vs `a-b`) is documented as a test.
  - **P13c · Carry up** ✅ — per-function oracle-free properties become a HARD
    `ModulePropertyGate`; per-function exact cases demoted to SOFT. round_trip goes hard
    (the inverse sibling is in scope). The app inherits it transitively via `build_module`;
    cross-function behavior stays hard via the IntegrationGate's relational snippets.
  - **P13d · Graded-confidence oracle (soft-tier upgrade)** ✅ — `oracle.py` VotingOracle +
    SOFT `ConsensusGate` (opt-in via `build_software(oracle=...)`): re-derives the expected
    value across N independent draws / models, reports *agreement* as graded confidence, and
    flags code that disagrees with the consensus as a strong advisory — never a hard block.
    Stays SOFT on purpose: cross-model agreement is correlated (shared training bias), so it
    raises confidence not certainty. The only path to HARD for a value is an *independent
    second method* (differential testing), not more votes from the same kind of guesser.
    Verified live on Sonnet (unanimous re-derivation, high-confidence confirmation).
- **P14 · Second org type** (Sep–Nov) — stand up an org with a **genuinely different
  verification model** on the *unchanged* engine — e.g. a research/docs org gated by
  citation integrity, claim-to-source grounding, and internal consistency (a topic with no
  code to run). *Done: a non-software org runs on the same substrate — the reusability claim,
  proven, not asserted.*
- **P15 · Hub maturation** (Nov–Dec) — polish the app route; real run-history browsing,
  per-run telemetry, and an audit view over institutional memory. *Done: start, watch, and
  audit any run from the hub with nothing mocked.*
- **P16 · Hosting** (Dec–Feb) — sandboxed Executor (real isolation for bigger/untrusted
  builds) + DB-backed memory and run history. (The cloud model provider already landed
  early, alongside the toggle.) *Done: a build runs isolated, persisted to a real store.*
- **P17 · Bootstrap** (Feb–Apr) — point the proven org at building one real Veritas
  component (a new gate or role) under its own gates. The strange loop, earned — and only
  after it reliably builds ordinary apps. *Done: a Veritas part ships that the org built and
  its own gates accepted.*

---

## Reality reshaped the plan — where we actually are (updated 2026-06-19)

The phases above were the original sketch; the build took its own order. What actually shipped
(all pushed, 144 tests, mypy strict clean):

- **P14 ✅ Web Studio** — second org, verified by a real headless browser (render/layout/
  structure/a11y). The reusability proof.
- **P15 ✅ Languages** — the Language seam; Python + JavaScript verified end to end; more are config.
- **P16 ✅ Research Studio** — third org, verified by *grounding* (citations resolve, quotes verbatim).
- **P17 ✅ Hub maturation** — browsable run history, per-run telemetry, memory audit, live timeline.
- **P18 ✅ Bootstrap** — the org built a real Veritas component (`estimate_tokens`) under its own
  gates; it now powers hub telemetry. The strange loop, closed.

Three genuinely different verification models (execute / render / ground) run side by side on one
unchanged engine, in a matured hub. The original thesis is demonstrated.

## The road ahead — Create Mode (P19→P24)

The next arc unifies the generative suite + the interview tools + Veritas under one thesis: a
**create mode** alongside verify mode. Verify mode = the machine is the gate. Create mode = *you*
are the gate for feel, the **interview manufactures checkable criteria** so as much as possible is
hard-gated, and the system **learns your taste** from your sign-offs. Not a new org — a mode + a new
verification tier (human/profile), first home = Web Studio. Invariant across both: every artifact is
tagged by *who verified what* (`machine-proven` / `model-judged` / `human-approved`) — nothing is
ever shown as more verified than it is.

- **P19 · Measurable-aesthetic gates** — extend the browser executor to read computed styles; HARD
  gates check a render against *explicit* criteria (palette ⊆ set, contrast ≥ X, dark/light, fonts,
  spacing). No LLM. *Done: a page is hard-passed/failed on explicit aesthetic criteria; mutants caught.*
- **P20 · Interview → checkable spec** — an interview engine that asks until it can emit a spec
  specific enough for P19's gates to check it (the scene/beats "interview-until-it-scores" pattern).
  *Done: a vague goal becomes a gate-checkable spec; a too-vague spec is refused.*
- **P21 · Human-approval gate + human-approved memory** — build→review→approve-or-feedback
  (conversation-as-retry); approval persists as a `human-approved` record; trust ledger gains the
  third tier. *Done: an approved artifact ships labeled human-approved and lands in memory.*
- **P22 · Aesthetic profile** — consolidate `human-approved` records into a structured profile; feed
  it as interview defaults + standing gate checks. *Done: a related build asks fewer questions and
  pre-applies codified preferences.*
- **P23 · Semantic recall (embeddings)** — upgrade `recall()` to local embeddings; benchmark token
  vs. embeddings (accept-rate / retries). *Done: the benchmark shows recall measurably helps.*
- **P24 · The toggle + create mode in the hub** — verify=gate / create=annotate; the create-mode
  artifact (output + three-tier trust map); hub UI (interview chat, trust report, Approve, profile).
  *DONE: a Create view drives the unchanged `interview` → `build_create_page` engine from a
  background thread whose answer/review callbacks block on the human over HTTP. Interview chat,
  gateable-spec card, live candidate preview, three-tier trust map (machine-proven / model-judged
  (none) / human-approved), Approve + Request-changes, and a learned aesthetic-profile panel.
  Approval ships human-approved into web memory and compounds the profile. Verified end to end
  through the HTTP control plane (offline scripted test). Create mode is now complete in the UI.*

## The road ahead — Production Studio + new orgs (P25→P27)

A 4th org landed: **Production Studio**, verified by *consistency through the chain* (the concept
declares the entities, the script may use only those, the storyboard covers only real beats and
shows only a beat's entities — referential integrity a machine can prove; "compelling" is the
human tier). Each phase below is built **stub-first** (deterministic placeholder, prove the gates)
then the real engine is swapped behind the seam — the pattern that worked everywhere else.

- **P25a · Structural spine** — concept → script → storyboard as typed artifacts; gates for
  completeness, grounding (no undeclared entity), and coverage (no dropped beat). *Done: a coherent
  production ships the whole chain; an undeclared character / dropped beat / orphan shot each trips
  the owning gate; live qwen refused a script that invented characters.*
- **P25b · Asset generation** — *verification: integrity + coverage.* Each shot → an image, each
  beat's narration → TTS audio, behind an `AssetGenerator` seam (StubGenerator offline; real
  image-gen + TTS later). HARD gates: AssetCoverage (an asset per shot/beat), AssetIntegrity (each
  image decodes at expected size, each audio has duration > 0). *Done: StubGenerator writes real
  png/wav (stdlib only, no PIL); coverage catches a missing frame, integrity catches a corrupt or
  mislabeled file; the full chain ships 4 stages; ffprobe independently confirms the media is valid.*
- **P25c · Visual consistency** — *verification: consistency via measurable signal.* Each entity
  gets a pinned reference (seed/reference image); the gate checks each shot image against it
  (perceptual/embedding similarity within tolerance). The "maintain consistency" guarantee made
  checkable. *Done: the manifest records the reference each entity was drawn with per shot;
  AssetConsistencyGate (HARD) proves an entity's reference never drifts across the shots it appears
  in; the stub draws each entity from its pinned reference so a recurring character renders
  byte-identical; a tampered reference is caught.*
- **P25d · Editing / assembly** — *verification: conformance + temporal integrity.* Assemble shots
  + narration into a timeline. HARD gates: SequenceCoverage (every shot, in storyboard order),
  TimelineIntegrity (shot duration = its audio's, total within target, no gaps/overlaps). *Done: a
  deterministic Editor lays shots in order and splits a multi-shot beat's audio across its shots;
  SequenceCoverage catches a reorder, TimelineIntegrity catches a gap and a sync drift; the full
  chain ships 5 stages (concept→script→storyboard→assets→timeline).*
- **P25e · Publishing** — *verification: format/codec compliance + file integrity* (my-AI-scene's
  model). Render the timeline to MP4 (ffmpeg) or a web bundle. HARD gates: PublishFormat (codec/
  resolution/aspect/duration meets the platform profile), OutputIntegrity (decodes/plays, duration
  matches the timeline). *Done: FfmpegPublisher renders a real MP4 (image sequence + per-beat
  narration, muxed); gates read the output back with ffprobe (trust the file, not the renderer);
  full chain ships 6 stages and produced a real h264/aac 640x360 8.0s file matching the timeline.*
- **P25f · Taste tier (create-mode for production)** — *verification: human-approved + profile
  learns style.* The residue the gates can't touch ("is it good?"). Reuses the create-mode tier:
  a human approves the final cut, the interview front-loads checkable style criteria. This is where
  the "QA agent" actually lives — QA is the gate layer across P25, not a separate proposer. *Done:
  build_create_production runs the whole chain (the machine floor) then a human judges the residue;
  approve → a human-approved memory record + the production style profile compounds (tone/resolution/
  length) and seeds the next brief; request-changes amends the brief and re-runs; a machine-floor
  failure never reaches the human. **P25 — Production Studio — is COMPLETE.***

- **P26 · Empirical / Research Lab org** — *verification model: **reproducibility** — a hypothesis
  is accepted only if a re-runnable experiment supports it.* Seeded by the existing `bench/`.
  **P26a** Experiment artifact + `ExperimentRunner` seam + ReproducibilityGate (re-run, results
  match within tolerance) + ResultSupportsHypothesisGate. **P26b** cast (Director/LitReview/
  Hypothesis/Experiment/Writer as proposers; Critic & Validation = gates) + grounding gate for the
  lit review (reuses Research). **P26c** register in hub; the demo is the project's own question —
  "do local LLM ensembles beat frontier models?"

- **P27 · Presets** — not new engine; each is *cast + pipeline on an existing verification model*,
  proving the substrate generalizes. **Newsroom** = Research + fact-checker role. **Education** =
  Research grounding + a pedagogical-structure gate (bridges to myAIstro). **Startup Factory** =
  orchestration Research → Web → Software ("profitable?" stays a human bet). **Game Studio** =
  Production + Software composed.

**Not Veritas** (a different machine — emergent simulation, "script incentives not outcomes," no
artifact + no gate): Civilization Simulator, AI Dungeon Master, Company Simulator. These belong to
the the-house-always-wins / Memory Economy City thread, not here.

## Parallel / later tracks

- **Hosting** — sandboxed Executor + DB-backed memory (local → shippable).
- **More languages** — Rust / Ruby / C are a `Language` each.
- **More bootstrap targets** — let the org build more of itself.
