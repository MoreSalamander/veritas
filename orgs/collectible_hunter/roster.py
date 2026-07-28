"""The collectible-hunter org's roster, as structured data for the Hub's Org
view.

Unlike the in-repo studios, this cast and these gates live in the org's own
codebase (~/MoreSalamander/collectible-hunter). The descriptions are authored
here; the cast mirrors that repo's own engine/roster.py, and the checks
mirror the shared hunter_engine.gate.Gate every Hunter engine uses — HARD,
fail-closed, and the only path to a trusted record.
"""

from __future__ import annotations

from typing import Any

# (display name, role, what it produces) — proposers; they decide nothing.
_CAST: list[tuple[str, str, str]] = [
    ("Sold-Comps Scout", "scout", "Candidate collectible specs from active listings vs. sold comps — untrusted by construction."),
    ("Grading-Pop Scout", "scout", "Candidate specs corroborating a claimed grade/rarity against population reports."),
    ("Source Verification Agent", "verifier", "Independent confirming comps and listing sources attached as positive evidence."),
    ("Scam Detection Agent", "verifier", "Fake-listing/counterfeit-slab scam reports attached as negative evidence — the org's standing red team."),
    ("Opportunity Ranking Agent", "analyst", "A reward-potential proposal (0-40, clamped) plus an evidence-cited narrative."),
    ("Debate: Advocate", "debate", "The strongest honest case FOR each verified opportunity — transcript only."),
    ("Debate: Skeptic", "debate", "The danger case: authenticity, condition, and liquidity risk — its only teeth are scam reports the gate counts."),
    ("Debate: Strategist", "debate", "The fit case against the user's profile — transcript only."),
    ("Portfolio Strategy Agent", "strategy", "A voiced strategy note over the deterministically selected mission."),
    ("Explainer", "coach", "Translates grading/collecting jargon into plain English."),
]

# (name, determinism, about) — the shared hunter_engine.gate.Gate checks,
# identical across every Hunter engine (crypto/collectible/free-money). All
# HARD; the gate fails closed.
_GATES: list[tuple[str, str, str]] = [
    ("scaffold:known_scam_list", "hard", "any source domain on the curated scam list is a hard fail — taint is a red flag, not evidence"),
    ("scaffold:official_domain_allowlist", "hard", "at least one source on the official/aggregator allowlist (subdomain-aware)"),
    ("scaffold:source_validity", "hard", "per-source validity: official, or RDAP-aged past the floor; invalid sources are excluded, never decisive"),
    ("scaffold:multi_source_confirmation", "hard", "enough VALID domains confirm (official presence suffices); more evidence can only help"),
    ("scaffold:contract_verified", "hard", "not applicable to physical collectibles; passes trivially when no on-chain claim is made"),
    ("scaffold:scam_report_evidence", "hard", "one credible scam report is a hard fail; unresolved reports fail closed; reports follow the item across listing variants"),
    ("rubric:score_clamp", "hard", "cost/time/safety computed in code from spec + gate evidence; the LLM proposes only reward-potential, clamped 0-40"),
    ("mission:caps_and_floors", "hard", "mission selection is greedy-by-score within the profile's time/budget caps and risk/score floors"),
]


def roster() -> dict[str, Any]:
    return {
        "cast": [{"name": n, "role": r, "produces": p} for n, r, p in _CAST],
        "gates": [
            {"name": n, "determinism": d, "scope": "opportunity", "about": a}
            for n, d, a in _GATES
        ],
        "principle": "Free agents at the edges, one deterministic fail-closed gate at the "
        "center. Debate stances are transcript, never verdict — the only way any agent "
        "changes an outcome is by filing evidence the gate counts.",
    }
