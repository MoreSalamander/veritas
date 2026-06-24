# Veritas Dynamics — Claude Code instructions

Reliable autonomous organizations. An LLM **proposes**; a deterministic scaffold (typed
artifacts, machine-checkable gates, provenance, institutional memory) **decides**. We're
building a *trust system*, not a cleverer agent. README.md = doctrine, ROADMAP.md = phases.

## Setup
```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium   # Web Studio renders in a real browser
```
Python 3.11+. Local models via Ollama (default star `gemma4:12b`; also qwen3.5, llama3.1).
Cloud models read `ANTHROPIC_API_KEY` from `.env` (gitignored) — remind the user to rotate it.

## Before every commit — the gate
```
.venv/bin/pytest -q          # all green, no exceptions
.venv/bin/mypy               # strict; config targets engine/ orgs/ hub/
```
Both must pass. New behavior ships with a test. Commit/push only when asked.

## Run the hub
```
VERITAS_DATA=./hub_data .venv/bin/uvicorn hub.app:app --port 8099
```
- **Never `rm -rf hub_data`** — it holds the user's real runs/memory/profiles. Restart without wiping.
- uvicorn has no `--reload` here: after editing `hub/`, restart the process to serve changes.
- The hub UI can't be live-verified from inside Claude Code reliably (the user runs it). Keep
  changes verifiable: TestClient tests + `node --check` the inline `<script>`; the user eyeballs.

## Layout
- `engine/` — the substrate: Artifact, Gate, Memory, Run, Executor, Validation, model seam. Org-agnostic.
- `orgs/` — each org = a cast (proposers) + domain gates. `registry.py` is the catalog the hub reads.
- `hub/` — FastAPI control plane + the single-file UI (`hub/static/index.html`). `ingest.py` = the
  transcript-fetcher seam (yt-dlp) feeding the Second Brain (the cross-org `memory/commons/` knowledge store).
- `bench/` — measurement harnesses (`run_bench.py`, `selfconsistency.py`); `RESULTS.md` is curated.
- `docs/` — `about.html` (explainer), design notes.

## The doctrine (governs every change)
1. **An org is defined by its verification model** — *how it knows an artifact is true*. Same
   verification model → same org, different ROLE. Different model → different ORG. "It makes a
   different artifact" is not enough; ask what *verifies* it.
2. **Gates declare HARD or SOFT honestly.** Accept iff ≥1 HARD gate passed AND every HARD gate
   passed. **Zero hard gates can never accept.** SOFT (incl. LLM judges) can flag, never block.
3. **Never show something as more verified than it is.** Trust tiers: machine-proven (hard gates) ·
   model-judged (soft) · human-approved (create mode, a person signed off the output) · **human-vouched**
   (Second Brain commons — a person curated the *source*, but nothing checked its *claims*). Tag every
   artifact by who verified it. A human-vouched source may ground only an **attributed** claim ("Source X
   states Y"), never a factual one ("Y is true") — that containment is `VouchedAttributionGate` (P28).
4. **The model is swappable.** Every model call goes through `engine/model.py`'s `ModelProvider`
   seam. Tests use `ScriptedProvider`/`SequencedProvider` (offline, deterministic) — never a live model.
5. **Memory only counts if retrieved at similar-task-start.** Failures/lessons are recalled and fed
   to proposers before they propose.
6. **Measure before you build.** New verification mechanisms earn their place on data (see
   `bench/RESULTS.md`), not intuition.

## Gotchas (real, durable)
- FastAPI body models (`BaseModel`) MUST be module-level, not nested in `create_app` — with
  `from __future__ import annotations` nested ones break body resolution (422).
- Ollama reasoning models return empty responses unless thinking is handled: `OllamaProvider`
  sends `think=False` by default; thinking is adaptive (on for module/app builds via `for_shape`).
- ffmpeg concat lists use **basenames** (assets are siblings of the list file) — full cwd-relative
  paths double the prefix under a relative data dir.
