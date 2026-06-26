# Veritas Dynamics — Roadmap

Companion to [README.md](README.md) (the founding doc). The README is *what & why*.
This is *in what order, and how we know each phase is real.*

---

## Three principles that shape the whole sequence

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

**3. The gates are governed too (the reflexive rule).**
No new verification mechanism — a gate, a confidence signal, a scoring heuristic — is trusted on a
one-off or irreproducible measurement. Its central claim must first clear the system's own empirical
bar: framed as a hypothesis, supported by a *reproducible* experiment, passed through the Empirical
Lab's gates. Until then it ships disabled or labelled exploratory, never as a gate. The system gates
its own evolution. (See README §4.5. First instance: the confidence layer's confident-wrong bound,
formalized in `bench/experiments/confidence_self_consistency.py` and asserted in
`tests/test_confidence_experiment.py`.)

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
  *DONE (core): orgs/empirical_lab — Hypothesis (statement + machine-checkable prediction: compare or
  threshold on a metric) → Experiment code (SECURITY-SCANNED before it is ever run, reusing the
  software org's scan) → run it repeatedly → the result is judged by ExperimentRuns + Reproducibility
  (independent runs match) + SupportsHypothesis (the measured DATA, not the model, satisfies the
  prediction; a refuted claim is rejected and remembered). Cast = Scientist + Experimentalist +
  Experiment Runner (a tool); Critic/Validation are gates. Registered as the 5th org. 6 tests: a
  supported+reproducible claim ships; a refuted one, a non-reproducible one, and a dangerous
  experiment are each refused by the owning gate. Live qwen: hypothesis + safe experiment shipped,
  but the experiment errored at runtime → result REFUSED (no false green). FOLLOW-UPS: a grounded
  lit-review role (reuse Research grounding) + a report Writer; wire real model-vs-model experiments
  (the literal "ensembles vs frontier" run) behind the ExperimentRunner.*

- **P27 · Presets** — not new engine; each is *cast + pipeline on an existing verification model*,
  proving the substrate generalizes. *DONE: orgs/presets.py shows both mechanisms. REUSE — Newsroom
  (`build_article`) and Education (`build_lesson`) run the Research org's grounding pipeline unchanged,
  same gates, different product framing. COMPOSE — Startup (`build_startup`) chains the Web org (a
  landing page) + the Software org (an MVP function); Game (`build_game`) chains the Production org +
  the Software org; the pure `_combine` accepts only if every part shipped, and "profitable?"/"fun?"
  stay honest human bets. All four registered (9 orgs total: 5 models + 4 presets); 3 tests (article
  + lesson ship on grounding; the combiner's all-parts-shipped logic). The verification thesis is
  fully demonstrated — five models, and products built by reusing and composing them.*

- **P28 · The Second Brain — a cross-org knowledge commons** — *verification model: **containment**,
  not content. The commons holds material the human curated but no gate has fact-checked; the org's
  job is to keep it labeled and quarantined forever. Done-when for the rung: every commons record
  carries a resolvable origin + a `human-vouched` tag, and that tag provably survives into any
  provenance that touches it; no gate ever promotes a commons record to fact.* The existing per-org
  memory (`hub_data/memory/<org>/`) stays untouched and visually isolated — it is *produced* output.
  The commons is a new, parallel `MemoryStore(base / "memory" / "commons")` of *ingested* input, a new
  `category="source"`, reusing the proven YAML-frontmatter + `index.md` format verbatim. **Curation is
  real verification of the *source*, not its *claims*:** the human vouches "this is a worthwhile source"
  (earning `human-vouched`, the P21 tier) — they do not vouch that every sentence in the transcript is
  true. So the consumption rule is **attributed-vs-factual**: a grounding gate may cite the commons for
  *"Source X states Y"* (verifiable — the quote is verbatim, the source is vouched) but may **never**
  ground *"Y is true"* on it (its truth was checked by no one). Sibling of **P23** — the commons is the
  first store that outgrows `recall()`'s `load_all()`, so it makes P23's embedding-backed recall load-bearing.
  - **P28a · The commons store** — `MemoryStore` at `memory/commons/` + `MemoryRecord.from_source(url,
    channel, transcript, captured_why)` → `category="source"`, `human-vouched` frontmatter; a "Second
    Brain" nav entry that lists/searches it and appears in **no** org tab. *DONE (2026-06-23): engine/memory.py
    `from_source` + `TRUST_VOUCHED` + a persist-time containment guard (a source record without a resolvable
    origin AND the human-vouched tag is refused at persist — unverified material lives in the commons only while
    labeled). hub/app.py: a parallel `MemoryStore(base/"memory"/"commons")`, GET/POST `/api/commons` (manual
    transcript entry; no-origin → 400). hub UI: a "Second Brain" nav entry + view (add form + ◆ human-vouched
    cards) under its own "Knowledge" group, in no org tab. 6 tests (tests/test_commons.py + test_hub_commons.py),
    267 pass, mypy clean. Verified live on an isolated instance: save → list → 400-on-no-origin.*
  - **P28b · Manual ingest (URL paste)** — paste a YouTube URL → fetch transcript → `from_source` → persist.
    No share-sheet yet; prove the spine with paste. *DONE (2026-06-23): hub/ingest.py = a `TranscriptFetcher`
    seam (ABC) with `YtDlpFetcher` (captions via yt-dlp — manual subs preferred, auto-captions fallback,
    json3/VTT parsed to clean text; downloads through yt-dlp's own HTTP client so it inherits TLS/headers) and
    `ScriptedFetcher` so tests stay offline; `TranscriptUnavailable` is the fail-honestly signal. `/api/commons`
    now fetches when no transcript is pasted (URL is the primary flow; manual paste is the fallback), 422s with a
    clear message on no-captions/unreadable URLs, persists nothing junk. yt-dlp added to the hub extra +
    mypy override. 11 commons/ingest tests (parsers, scripted fetch+fail, URL→fetch→persist, fail-honestly),
    272 pass, mypy clean (67 files). Verified LIVE: a real YouTube URL → title/channel + 2029-char transcript
    persisted human-vouched; a non-video URL → 422.*
  - **P28c1 · Opt-in consumption — the trust mechanics (the thesis-proving rung).** Pass a commons-store
    handle into one org's pipeline (Research first; a real signature/plumbing change through `hub/app.py`, not
    a one-liner). Prove the *containment under consumption* on a deliberately trivial corpus (one source, so
    retrieval is not a variable and can't mask the gate) — this is the first rung where the commons meets a
    gate, and it meets it at the seam laundering would slip through (grounding's verbatim-quote check). Kept
    small and isolated on purpose: retrieval engineering must not contaminate whether the gate actually holds
    the line. *DONE (2026-06-24): orgs/research_studio/gates.py `VouchedAttributionGate` (HARD) — a claim citing
    a commons source must NAME (attribute) that source in its text, else it's stating unverified material as
    fact → refused. The deterministic signature of honest framing: an attributed claim names its source; it
    can't be gamed harmfully because laundering would require writing "According to X, …", which is the honest
    attributed form we allow. pipeline.py: `build_report(..., vouched=)` maps commons source id → attribution
    label, adds the gate, and folds the commons ids into `informed_by` so the unverified provenance travels with
    the output. Gate added to the research roster. Tests (tests/test_research_vouched.py): the crux — identical
    citation + identical verbatim quote, ONLY the framing differs → "According to Rick Astley, the sky is green"
    PASSES, bare "The sky is green" REFUSES; verified-tier sources untouched; pipeline accepts attributed +
    carries commons provenance, refuses factual. 277 pass, mypy clean. NOTE: feeding commons sources into a hub
    Research run is retrieval = P28c2; c1 deliberately proves the containment on a trivial corpus so retrieval
    can't mask whether the gate holds.*
  - **P28c2 · Passage retrieval — the scaling rung.** A whole transcript is the wrong unit to *recall* (a long
    document matches almost any query and dumps 50k chars into the proposer's prompt) — but the right unit to
    *store* (one source = one artifact, one provenance, one trust tag; storing the whole body is strictly more
    information than chunks, and you can always derive passages but never un-chunk). So passages are a READ-path
    transform, not a storage change: split each source into passages, rank passages, return the top few, each
    still carrying its parent source's id/url/trust. Leaves `from_source`/the record untouched and the org's
    proven `recall()` untouched. **Merges with P23** — passage-level is also the right granularity for embeddings
    (which degrade on long text), so do the embedding work here, on passages. *Done: recall against a many-source
    commons returns relevant PASSAGES (not whole transcripts) with parent provenance intact; a benchmark shows
    passage recall beats whole-source recall on relevance at commons scale.*
  - **P28d · Intent router (optional, deferrable)** — at ingest, "make software / make a video / write a
    paper" spawns the matching org's run seeded with the commons record id. *Done: one ingest-with-intent
    produces an org run whose output traces back to the source record.* (Explicitly optional — the store +
    paste + consumption is the whole value; this never blocks them.)
  - **P28e · Share hop** — *only now* the iOS Shortcut / browser extension that POSTs a URL to P28b. The last
    mile, on a proven pipeline. *Done: sharing from the YouTube app lands a record in the commons end to end.*

**Not Veritas** (a different machine — emergent simulation, "script incentives not outcomes," no
artifact + no gate): Civilization Simulator, AI Dungeon Master, Company Simulator. These belong to
the the-house-always-wins / Memory Economy City thread, not here.

## Parallel / later tracks

- **Hosting** — sandboxed Executor + DB-backed memory (local → shippable).
- **More languages** — Rust / Ruby / C are a `Language` each.
- **More bootstrap targets** — let the org build more of itself.
