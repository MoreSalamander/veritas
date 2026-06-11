# Veritas Dynamics
### Reliability as Architecture: Treating LLMs as Proposal Engines Inside Deterministic Decision Systems
*A research proposal — June 2026*

---

## Abstract

Large language models are powerful generators and unreliable deciders. The dominant response — *agents* — compounds that unreliability by letting the model both propose actions and judge their correctness, so the system is only ever as trustworthy as the model's worst moment. **Veritas Dynamics** proposes the inverse architecture: the LLM is confined to the role of *proposal engine*, and a deterministic scaffold holds exclusive authority as the *decision engine*. The model may suggest; only verifiable, code-level gates may accept. We hypothesize that reliability is not a property to be coaxed out of a model through better prompting, but a property to be **engineered around it** — and we present a working system that bootstraps software end-to-end under this constraint.

## 1. Problem

The field is converging on a single failure mode. When an LLM is asked to write code *and* asked to decide whether that code is correct, both judgments are drawn from the same fallible distribution. A confident wrong answer passes its own review. Reliability under this design is statistical and non-monotonic: it improves with model scale but never becomes a *guarantee*, because nothing in the architecture is categorically incapable of accepting a bad result.

This is the wall every autonomous-agent effort hits. The question Veritas asks is not "how do we make the model more reliable?" but "**how do we build a system that is reliable even though the model is not?**"

## 2. Thesis

> *LLMs are not reliable; systems can be.*

The model proposes; the scaffold decides. The unit we are building is not an agent — it is a **trust system**. Its governing doctrine is four phases, in strict order:

**Explain → Synthesize → Verify → Persist.**

A proposal is explained, synthesized into a typed artifact, verified by deterministic gates, and only then persisted to institutional memory. Judgment never substitutes for verification at any boundary.

## 3. Architecture

The system reduces to two primitives:

- **Artifact** — a typed, owned, provenance-stamped unit of work (a spec, a function, a test, a package, an entrypoint). Every artifact carries the record of what informed it and which gates ruled on it.
- **Gate** — a pure function `Artifact → (pass | fail, evidence)`. Each gate declares itself **HARD** or **SOFT**.

From these falls the **core invariant**, enforced in the state machine itself: *a run with zero HARD gates can never accept anything.* Soft gates advise; hard gates decide; the two are never confused. A system cannot pass on judgment alone — by construction, not by convention.

Three design choices give the framework its reach:

1. **Organizations are defined by their verification model, not their subject.** Two casts of agents that *check correctness the same way* are one organization wearing two hats; two that check differently are genuinely separate organizations on a shared substrate. This is what makes the framework general rather than a single hard-coded pipeline.
2. **Oracle-free verification.** Where possible, gates test *metamorphic* properties — round-trips, invariants, fixed points — rather than LLM-authored value oracles, removing the model from the position of asserting ground truth.
3. **Retry the implementation, never the judge.** On failure, the engine re-runs the *proposer* with the gate's evidence as feedback. The test-authors are never re-rolled to make a failing implementation pass — closing the loophole that quietly defeats most self-correcting agents.

All external dependencies sit behind swappable seams (`ModelProvider`, `Executor`, `MemoryStore`), so the development substrate (a local 8B model, files on disk) and the production substrate (a frontier API, a sandbox, a database) are the same architecture under different backends.

## 4. Preliminary Results

The first organization built under this framework is a **software studio** that bootstraps itself — it is the org that builds the system as it learns how to build the system. Implemented across twelve sequential phases (P0–P12), it currently takes a natural-language goal and autonomously produces a **plan → multiple coexisting modules → an assembled package → an entrypoint → an end-to-end-verified runnable application.**

On a frontier model, a representative build (a multi-operation temperature toolkit) was **accepted green, end-to-end, with zero retries, for roughly $0.25.** Critically, the same pipeline on a small local model fails in *diagnosable, model-attributable* ways — confirming that the residual failures live in the proposer, exactly where the architecture predicts, and not in the decision layer. Institutional memory now persists both past *failures* and past *structural decisions*, so the org grows more consistent with itself over time.

## 5. Contribution & Novelty

The contribution is a falsifiable claim made buildable: **that trust in an LLM-driven system can be relocated from the model into the architecture surrounding it, and that doing so is the path to systems that are reliable rather than merely impressive.** We are not racing to be first to the *idea* of autonomous organizations — that destination is crowded. We are building the first *trustworthy* version: the verified floor that other work has to stand on. First-to-last, not first-to-flag.

## 6. Vision: One Engine, Many Organizations

The software studio is not the product — it is the **first proof** that the product is general.

The engine is deliberately domain-blind. It manipulates typed artifacts, runs gates, enforces the hard/soft invariant, retries proposers against evidence, and persists what survives. Nothing in that machinery mentions code. This means a new organization is not a new system — it is the *same* system supplied with a different cast and, crucially, a **different verification model**. That single substitution is the entire act of creating a new domain.

The consequence is a **federation of organizations running on one engine**, each trustworthy in its own terms:

- a **software** org that verifies by execution, types, and end-to-end tests;
- a **research / documentation** org that verifies by citation integrity, claim-to-source grounding, and internal consistency — a topic about bald eagles has no code to run, so it is genuinely a *different organization*, not a role inside software;
- a **music** org that verifies a generated piece against structural and spectral checks;
- a **video** org that verifies a render against shot-list and continuity invariants;
- and, in principle, **any domain where correctness can be written down as a deterministic check** — finance, scientific computing, legal drafting, data pipelines.

This is not speculative reach. Five domain tools predated Veritas and were each, in hindsight, a *partial* instance of this one pattern — a generator paired with a checker. Veritas is the generalization they were all circling: extract the proposal-engine/decision-engine split into a single substrate, and the domains become *configurations* of it rather than separate codebases.

The unifying surface is the **hub** — the place organizations live, are run, observed, and audited. One operator describes a goal in plain language; the hub routes it to the organization whose verification model fits; the engine does the rest under the same guarantees regardless of domain. The promise is not "an AI that can do anything," but a *single trust architecture* under which many different kinds of work can each be made reliable — held to a standard the domain itself defines, and never accepted on the model's word alone.

## 7. Roadmap

A ~10-month arc: harden the verification layer (structured oracles removing raw LLM assertions from hard gates entirely), prove substrate-reuse by standing up a **second organization with a genuinely different verification model**, and mature the central hub through which organizations are run, observed, and audited.

---

*Veritas Dynamics is part of the MoreSalamander studio — built by the engineer learning how to build it.*
