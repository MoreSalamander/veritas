# Software Studio — the Roster

The software org = **a cast of proposers** (they suggest; they decide nothing) **+ a
decision engine of gates** (they decide; they never propose). The split is the whole
thesis: the LLM is a proposal engine, the deterministic scaffold is the decision engine.

The one rule that ties it together: **a run with zero HARD gates can never accept
anything.** The cast can be as persuasive as it likes — nothing reaches memory on
judgment alone.

---

## The cast — proposers

Each emits a typed, provenance-stamped artifact. Whether it lives or dies is entirely the
gates' call.

| Agent | role | Produces |
|---|---|---|
| **Router** | `router` | A soft pre-decision: is this goal a *function*, a *module*, or an *app*? Picks the pipeline. (Judgment only — whatever it picks is still hard-gated.) |
| **Spec Agent** | `spec` | An *executable* spec from a goal — function name, signature, cases, and oracle-free properties. Prose is rejected; only a spec the scorer can turn into checks survives. |
| **Developer Agent** | `developer` | The function's source code from the spec. On rejection, re-writes seeing the failing gates' evidence. |
| **QA Agent** | `qa` | Independent edge-case tests, written from the spec *without seeing the code* — so the reviewer never reviews its own assumptions. |
| **Doc Agent** | `doc` | Markdown documentation whose examples are run against the real function. (A *role* in this org, not a separate org — it verifies the same way: execute the code.) |
| **Architect Agent** | `architect` | A module *contract*: which functions exist, their signatures, cases, and per-function properties. |
| **PM Agent** | `pm` | Acceptance as *executable* tests — relational/round-trip checks that exercise multiple functions together (and, at app scale, designs `main()`'s contract). |
| **Module Developer** | `developer` | Source for every function in a module contract; self-corrects on rejection. |
| **Planner Agent** | `planner` | A *plan* for a goal too big for one module — a list of module briefs. No code, just the decomposition. |
| **Integrator Agent** | `integrator` | The app entrypoint `main()` that composes the modules to satisfy the PM's end-to-end tests. |

---

## The decision engine — gates

Every **HARD** gate is machine-checkable and asks no LLM anything. **SOFT** gates advise
but can never block. Validation is the final authority and only ever counts the hard
gates.

### Function level
- `spec-scorer` **HARD** — the spec is executable (has cases or properties)
- `syntax` **HARD** — parses and defines the named function
- `properties` **HARD** — oracle-free relations hold (round-trip, monotonic, invariant, idempotent) — *the behavioral authority*
- `acceptance-tests` **SOFT** — exact-value cases (a model-authored oracle → advisory)
- `security-scan` **HARD** — deterministic static scan for dangerous calls
- `qa-review` **SOFT** — QA's independent cases (its oracle is also an LLM → advisory)
- `consensus` **SOFT** — voting oracle's graded confidence (opt-in)
- `examples-run` **HARD** — every doc example actually runs against the real code
- `validation` **HARD** — final authority: all hard gates passed, provenance complete

### Module level
- `contract` **HARD** — the module contract is usable (≥2 functions)
- `integration-spec` **HARD** — the PM's tests touch ≥2 functions
- `module-syntax` **HARD** — every contracted function is defined
- `properties` **HARD** — per-function oracle-free relations (round-trip goes hard here — the inverse sibling is in scope)
- `acceptance-tests` **SOFT** — per-function exact cases (advisory)
- `integration` **HARD** — the functions work *together*, not just alone
- `validation` **HARD**

### App level
- `plan` **HARD** — the plan is a usable multi-module decomposition
- `assembly` **HARD** — the modules coexist (no name clashes, loads clean)
- `entrypoint` **HARD** — `main()` is defined and loads with the package
- `e2e-spec` **HARD** — the e2e tests actually drive `main()`
- `e2e` **HARD** — the whole app runs end-to-end
- `validation` **HARD**

---

*A role joins this org when it verifies the same way the org does (execute code, check
types, run tests). A capability that verifies a **different** way — citation integrity,
spectral analysis, continuity — is a different organization on the same engine, not a role
here. See README §6.5 (org-vs-role).*
