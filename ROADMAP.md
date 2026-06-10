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

### Phase 0 — The Spine  *(engine, offline, no LLM)*
The data model and the loop, before a single agent exists.
- **Build:** `Artifact` (typed, owned, status, full provenance) · `Gate`
  (interface declaring **hard|soft**, returns pass/fail + evidence) · `Memory` store
  (reuse myAIstro's file-per-record + frontmatter + index) · `Run` — the state machine
  that walks an artifact through Explain → Synthesize → Verify → Persist · the failure
  record.
- **Done when:** `pytest` green; a hand-built artifact pushed through a *stub passing*
  gate persists with a complete provenance trail, and through a *stub failing* gate lands
  in failure memory. Proposers are stubs. The loop is real even though nothing is smart yet.

### Phase 1 — One Honest Run  *(software_studio, minimal cast)*
The thesis, proven in the smallest unit that can prove it.
- **Build:** one narrow capability (e.g. "goal → one REST endpoint"). A **Spec** agent
  (one local proposer) → Spec artifact gated by a **spec-scorer** that *rejects any spec
  whose acceptance criteria aren't executable*. A **Developer** agent → code artifact
  gated by `pytest` + `mypy` + the generated acceptance-tests. Judge-separation anywhere a
  model judges.
- **Done when:** one run produces a genuinely gate-validated artifact in memory **and** a
  second run (bad spec or failing code) produces a real rejection in failure memory. The
  green is earned. This is the homerun swing in miniature.

### Phase 2 — The Cast  *(software_studio fills out)*
The full organization from the preview, made real.
- **Build:** Architect, QA, Security, Validation as additional proposers, each emitting a
  typed artifact (API-CONTRACT / PLAN / TEST / SECURITY-REPORT) behind its own gate.
  Full Explain→Synthesize→Verify→Persist with the real roster. Validation agent is the
  final gate before persist. Every persisted artifact carries a complete provenance trail
  (who made it / why / what validated it / why accepted).
- **Done when:** the e-commerce-style run from the preview happens *for real*, end to end,
  with at least one gate capable of halting or triggering a retry, and no artifact reaches
  memory without complete provenance.

### Phase 3 — The Org Learns  *(institutional memory goes active)*
Where "the system that learns how to build the system" stops being a slogan.
- **Build:** failure + lesson **retrieval** — when a new task starts, surface relevant
  past failures/lessons (tag or embedding match over institutional memory) into the
  proposer's context; the retry loop is informed by what was retrieved.
- **Done when:** a measurable drop in repeat failures across runs, and a run *visibly
  avoids* a mistake a prior run made — with the retrieved memory recorded in its
  provenance.

### Phase 4 — The Hub  *(control plane, extracted from what the org proved it needs)*
Now the central hub the organizations live in.
- **Build:** org **registry** (an org = substrate + a cast manifest; stand one up from
  config) · **Mission Control** API + dashboard fed by *real* telemetry · cross-org shared
  memory + governance · multi-project. Wire the AgentForge UI shape to the real engine.
- **Done when:** you start a run from the hub UI, watch real (not scripted) telemetry,
  and browse real institutional memory — all backed by the engine, nothing mocked.

### Phase 5 — Second Org Type  *(prove the reusability claim)*
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

P0–P5 + hub + registry are done. North star: **an autonomous org that reliably builds a
small-but-real multi-file app — the full cast earning their seats — and takes its first
proven step toward building its own parts.** The cast grows as the deliverable grows;
nothing earns a seat before there is something for it to verify.

- **P6 · Module** (Jun–Jul) — grow the unit from one function to a few-file module +
  integration test, all building green together. **Architect** (module boundaries /
  contract — validates against schema, types check) and **PM** (acceptance criteria as
  executable tests) earn real, gated seats.
- **P7 · App skeleton** (Aug–Oct) — modules compose into a runnable app (small API/CLI).
  New verifiable artifacts: API contract validates, end-to-end test runs. **CEO/PM**
  decompose a goal into modules/tickets; the **Memory** role earns its seat (decision
  records across the app).
- **P8 · Autonomy** (Oct–Dec) — the retry loop (rejection → re-propose with gate feedback)
  + scoring, so the org drives multi-step builds to a passing bar on its own; failure
  retrieval across the larger surface.
- **P9 · Hosting prep** (Dec–Feb) — sandboxed Executor (real isolation for bigger/untrusted
  builds), cloud model provider, DB-backed memory + run history. The deferred deployment work.
- **P10 · Bootstrap** (Feb–Apr) — point the proven org at building one real Veritas
  component (a new gate or role) under its own gates. The strange loop, earned — and only
  after it reliably builds ordinary apps.

### The fine rungs (single-job; phase numbers climb monotonically)

The milestones above are coarse targets; the actual work is finer rungs, each adding one
verifiable thing behind one gate. The next chunk, toward "a small running app":

- **P6 · Module** ✅ — function → module; Architect + PM gated; integration gate guards composition.
- **P7 · Unify + wire** ✅ — one `build(goal)` routes function vs module; hub rides on it.
- **P8 · Planner** — a goal too big for one module → a *plan* (list of module contracts).
  CEO/Planner earns a seat. Gate: `PlanGate`. Done: validated multi-module plan, no code.
- **P9 · Assembly** — build each planned module; prove they coexist (importable together,
  no name clashes). Gate: `AssemblyGate`. Done: plan → assembled package.
- **P10rung · Entrypoint + E2E** — app = modules + entrypoint (CLI) + end-to-end test.
  Integrator earns a seat. Gate: `E2EGate`. Done: goal → runnable small app, e2e green.
- **P11 · Memory seat** — decision records persisted and surfaced on related builds.
  Done: a build's decisions inform a later related build.
- **P12 · Retry loop** — on rejection, re-propose with gate feedback within the run
  (`run.attempt` + scoring). Done: fail → feedback → succeed, in one run. Autonomy begins.

Hosting (sandboxed Executor, cloud model, DB-backed memory) and the bootstrap stay past
this chunk.
