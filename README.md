# Veritas Dynamics

**Building reliable autonomous organizations.**

> LLMs are not reliable.
> Systems can be.

This is the founding document. It explains what Veritas is, how the idea arrived,
why it is different from most AI projects, and what gets built first. Everything
downstream — code, agents, schemas, milestones — descends from the ideas on this page.

---

## 1. Why this is different

Most AI projects have this shape:

```
LLM  →  Feature  →  Demo
```

Impressive for a few minutes. Thin underneath. The hard part was the prompt, and the
prompt is the part that doesn't hold.

This project has a different shape:

```
System Design
   ↓
Agent Architecture
   ↓
Memory
   ↓
Validation
   ↓
Autonomous Execution
   ↓
Emergent Behavior
```

The hard problems here are architecture, orchestration, memory, validation, and
emergence — not prompt engineering. That's a genuine engineering problem, and it stays
hard in a way that demos don't.

---

## 2. How this arrived

This wasn't a new idea. It was the idea that every previous project was circling.
Each one solved one face of the same shape without naming the whole:

| Earlier project          | What carries over            |
| ------------------------ | ---------------------------- |
| AI Civilization Simulator | Multiple autonomous actors   |
| Maestro / Knowledge OS    | Memory & institutional knowledge |
| AI Coding Tutor           | Verification against source material |
| Poker Coach               | Explain → Generate → Verify loop |
| Language Drift Engine     | Emergent behavior over time  |
| AI Research Lab in a Box  | Specialized agent roles      |

And the same DNA runs through the shipped tools:

- **myAIstro** — structured file-memory + *judge-separation* (the verifier never shares a model with the generator).
- **myAIscript** — interviews until the output passes a *pure-Python score* before any generation happens.
- **myAIscene / myAIbeats** — spec → generate → *verifier gate at every boundary* → persist.

Five tools, each a partial instance of one pattern: **constrain the probabilistic with
the deterministic.** Veritas is the whole shape — the framework the other five are
instances of. The difference from every earlier idea is that this one has immediate,
everyday practical value. You could use it tomorrow.

---

## 3. The core belief

Reliability does not come from a better model. It emerges when probabilistic
intelligence is constrained by deterministic validation, memory, governance, and
structured workflow.

So the reframe that changes everything:

- The **LLM is a proposal engine.** It produces candidates. Never facts.
- The **deterministic scaffold is the decision engine.** It accepts or rejects.

You are not building an agent. **You are building a trust system.**

Every workflow follows one loop:

```
Explain  →  Synthesize  →  Verify  →  Persist
```

- **Explain** — constraints, acceptance criteria, standards. No generation before constraints exist.
- **Synthesize** — agents produce work. Output is always a *proposal*, never a fact.
- **Verify** — deterministic evaluation wherever one exists. Pass or fail. No subjective acceptance.
- **Persist** — only validated output becomes organizational memory. Rejections are kept as failure records.

The organization learns from both what it accepted and what it rejected.

---

## 4. The Validation Doctrine

This is the heart of the project — not the coding agents.

Every artifact in the system carries a confidence trail. It is never just a file; it is
a file plus the full record of who made it, what checked it, and why it was accepted:

```yaml
artifact:        auth_service.py
created_by:      Backend Agent
validated_by:    QA Agent
security_review: passed
tests:           37/37
confidence:      0.97
status:          accepted
provenance:
  parent:        spec/auth-requirements
  rationale:     "implements AC-3..AC-9 of the auth spec"
  accepted_because: "all hard gates green; security scan clean"
```

From this, the organizational rules are not subsystems to build — they are just fields
on the artifact:

1. No agent trusts another agent by default.
2. Every artifact has an owner.
3. Every artifact has validation history.
4. Every decision is explainable.
5. Every accepted artifact has provenance: who made it, why it exists, what validated it, why it was accepted.

---

## 4.5 The reflexive rule — the gates are governed too

There is one move that can quietly rot a trust system from the inside: **adding a new way of
verifying, on the strength of a measurement that doesn't reproduce.** A clever new gate, a new
"confidence" signal, a heuristic that looked good once — wired in because a demo or a single run
seemed to support it. That is the same sin as a soft gate worn as hard, one level up: now the
*verification mechanism itself* is the unverified claim.

So the doctrine turns on itself:

> **No new verification mechanism is trusted until it has cleared the system's own empirical bar.**
> A signal that decides what counts as "verified" must first be shown — by a *reproducible*
> experiment — to measure what it claims to. Until then it ships disabled, or labelled exploratory,
> never as a gate.

This is enforced by the same machinery, not by good intentions: a proposed mechanism's central claim
becomes a **hypothesis** in the Empirical Lab (the reproducibility org), its supporting measurement
becomes a **frozen, re-runnable experiment**, and it earns trust only when the Reproducibility and
Supports-Hypothesis gates pass. The system gates its own evolution.

**First instance (live).** The knowledge mode's "confident" tier — answer from the model's own
knowledge, flag what's unreliable — rests on one number: how often a *confidently* asserted answer is
wrong. That bound was found by an exploratory live run (`bench/selfconsistency.py`), which by its
nature does not reproduce. So it was promoted: the run was frozen into a pinned transcript and the
bound recomputed deterministically (`bench/experiments/confidence_self_consistency.py`), where it
clears the Empirical Lab's gates — confident-wrong rate **5.9%**, below the 10% bar that lets the tier
ship *labelled* but (being above zero) never *verified*. The confidence layer earned its place by
passing the system it belongs to.

**Second instance (the strange loop).** The org's own proposers run on prompts. Changing one is a
verification-mechanism change, so it obeys the same rule: a measurement (`bench/promptbench.py`)
showed accept-rate moves *reproducibly* with prompt quality — and that a human-"cosmetic" reword was a
67-point regression, so prompt intuition can't be trusted, only the gate. That verdict is frozen into
an experiment (`bench/experiments/prompt_accept_rate.py`) that clears the Empirical Lab's gates
(`tests/test_prompt_experiment.py`): a proposer-prompt change is trusted only when its accept-rate
gain reproduces on a goal suite. The org gates its own prompts the way it gates everything else.

---

## 5. The foundational insight

If you were starting tomorrow, the first milestone is **not** "make an agent write code."

It is:

> **Make an agent produce work that can be objectively accepted or rejected.**

That single capability is the seed of the entire organization, because it unlocks a ladder:

```
acceptance / rejection
        ↓
     retries        (you can reject, so you can re-ask)
        ↓
     scoring        (you can rank attempts against criteria)
        ↓
     autonomy       (the system can drive its own retry loop to a passing bar)
        ↓
     teams          (multiple autonomous workers, each gated, composing work)
```

At the top of that ladder you are no longer building a coding assistant. You are
building **a software organization whose workers happen to be LLMs.**

---

## 6. The architecture that falls out of this

The honest engineering version of the vision. Two primitives carry the whole system.

**Artifact** — typed, owned, provenance-stamped. The struct *is* the trust system:

```
Artifact {
  id, type, owner_agent, parent_id,
  payload,
  provenance: { created_by, rationale, validated_by, gate_results, accepted_because },
  status: proposed | accepted | rejected,
  confidence
}
```

**Gate** — a function `Artifact → { pass | fail, evidence }`. Deterministic where one
exists; *explicitly soft* (human or judge-LLM) where one doesn't.

The "organization" is **a deterministic state machine over Artifacts, where agents fill
the proposal slots** — not a chatroom of agents talking to each other.

```
 Goal
  │
  ▼
┌────────┐ propose ┌──────────┐  GATE   ┌────────┐  accept → Memory (provenance-stamped)
│ Agent  │────────►│ Artifact │ ──────► │  Gate  │
│ (LLM)  │         │ (typed)  │         │(determ)│  reject → Failure Memory (diff + failing output)
└────────┘         └──────────┘         └────────┘
```

### Three hard truths this architecture respects

1. **Reliability is bounded by how much of the work can be reduced to a
   machine-checkable artifact.** Code has real gates (tests, types, schema, security
   scan). "Good requirement" and "right architecture" do not. Every gate must declare
   its determinism level — and a soft gate (LLM judging) must never be dressed up as a
   hard one. That honesty is the difference between a trust system and a polite committee
   of LLMs.

2. **The Spec is the load-bearing object, not the agents.** Don't accept prose
   requirements — accept requirements that *compile into machine-checkable acceptance
   criteria* (acceptance-criteria-as-tests). The forcing gate is a **spec scorer** that
   rejects any spec whose criteria aren't executable. Get this right and the downstream
   code gate becomes genuinely deterministic. (This is the myAIscript move, generalized.)

3. **Failure memory only earns its name if it's retrieved.** "The org learns from
   rejections" happens only when a past rejection surfaces *at the moment a similar task
   starts*. That's a retrieval problem, not an archive. It's where the learning claim
   lives or dies.

### Start with 3 roles, not 8

Every agent boundary injects fresh probabilistic noise that a gate must catch. More
agents = more proposals to verify = *more* unreliability. Begin with **Spec → Build →
Verify**, prove one green-to-memory cycle and one reject-to-failure cycle, then split
roles. Keep judge-separation: the verifying model is never the proposing model.

| Stage | Proposer | Artifact | Gate |
| --- | --- | --- | --- |
| Goal → Spec | Spec agent | Spec w/ acceptance-criteria-as-tests | **Spec scorer** (hard) — rejects non-executable criteria |
| Spec → Code | Developer | Code diff | tests + typecheck + acceptance-tests + security scan (hard) |
| Code → Memory | — | Validated artifact | provenance complete + all gates green → persist; else → failure memory |

CEO / strategy / roadmap / governance is a thin layer *above* this loop. Defer it. Don't
build governance for an organization that hasn't shipped one artifact.

---

## 6.5 What counts as an organization (the org-vs-role test)

A new *artifact* earns a new **role**. A new *way of knowing something is right* earns a
new **organization**.

An organization is defined by its **verification model** — how it decides an artifact is
trustworthy. Two kinds of work verified the *same* way are roles in one organization;
verified *differently*, they are separate organizations.

- Software is verified by **executing code** against a spec.
- Documenting code is verified by **executing the examples** — the same model. So the
  documentation writer is a *role in the software org*, not a peer (`DocAgent`): a doc
  whose example doesn't run is rejected exactly like a function that fails its tests, and
  its examples run against the real implementation so the docs can't drift from the code.

A genuinely separate org is one where "done" means something different: a **research
org** verified by source-grounding (every claim traces to a resolvable source), a
**production org** verified by format/duration/integrity. Those earn their own registry
entry. "It produces a different artifact" is never enough on its own — ask what
*verifies* it. This test governs every future org-vs-role decision.

---

## 7. Roadmap

- **M0 — The spine.** Artifact + Gate + provenance schema. Reuse the file-per-fact +
  frontmatter + index memory shape already proven in myAIstro. No LLM calls. Tests pass
  offline. *The data model is the foundation; everything hangs off it.*
- **M1 — One reliable loop.** A single narrow software task through Goal→Spec→Code→Verify→Persist
  with **hard gates only.** Success = one real provenance-stamped artifact in memory **and**
  one real rejection in failure memory.
- **M2 — Failure retrieval.** Surface relevant past rejections when a new task starts.
  Measure repeat-failure reduction. *This is the thesis test.*
- **M3 — Split roles.** Add separate QA / Security / Architect proposers — only once the
  loop holds.
- **M4 — Strategy + scale.** CEO/PM roadmap layer, multiple concurrent projects, and the
  generalization to other organization types (research lab, studio, school).

---

## 8. Risks / failure modes to design against

- **Soft gate worn as hard** — an LLM judgment treated as deterministic acceptance. Every gate declares its level.
- **Weak spec scorer** — prose leaks through and the code gate has nothing real to check.
- **Judge collusion** — verifier sharing a model with the proposer. Keep them separate.
- **Write-only failure memory** — rejections stored but never retrieved.
- **Agent sprawl** — accreting roles before M1 proves a single loop.
- **Laundered sources** — curated-but-unverified material (the Second Brain) treated as fact. A human
  vouches a *source* is worth keeping, not that its claims are true; so a vouched source may ground only an
  *attributed* claim ("Source X states Y"), never a factual one. The containment is checked, not trusted.
- **An ungoverned gate** — a new verification mechanism (a gate, a confidence signal) trusted on a
  one-off or irreproducible measurement. The unverified-claim problem, raised one level: the *verifier*
  is now the thing nobody checked. Defense is the reflexive rule (§4.5) — its claim clears the Empirical
  Lab's reproducibility gates before it may gate anything.

---

## 9. What this ultimately is

The framework must be reusable. Only the specialized agents change. The same spine runs
a software studio, a research lab, a production studio, a school. The first organization
— the Autonomous Software Studio — exists to build software. Its higher purpose is to
learn how an autonomous organization should think, remember, validate, govern, and
improve.

The system that learns how to build the system.

A software organization whose workers happen to be LLMs — where the hard problems are
architecture, memory, validation, and emergence, and the LLM is demoted to what it
actually is: a proposal engine, kept honest by a deterministic decision engine.

That's the project. That's what all the others were circling.
