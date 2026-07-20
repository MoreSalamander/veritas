"""The crypto-hunter org's roster, as structured data for the Hub's Org view.

Unlike the in-repo studios, this cast and these gates live in the org's own
codebase (~/MoreSalamander/crypto-hunter). The descriptions are authored here;
the checks listed mirror engine/gate.py there — HARD, fail-closed, and the
only path to a trusted record.
"""

from __future__ import annotations

from typing import Any

# (display name, role, what it produces) — proposers; they decide nothing.
_CAST: list[tuple[str, str, str]] = [
    ("Airdrop Scout", "scout", "Candidate airdrop specs from DeFiLlama's live pages — untrusted by construction."),
    ("Quest Scout", "scout", "Candidate quest/Learn&Earn specs from Galxe, Layer3, CoinMarketCap Earn."),
    ("Testnet Scout", "scout", "Candidate incentivized-testnet specs from chain sites and DeFiLlama."),
    ("NFT Scout", "scout", "Candidate ecosystem-mint specs from the major marketplaces."),
    ("Governance Scout", "scout", "Candidate DAO-participation specs from Snapshot and Tally."),
    ("Staking/DeFi Scout", "scout", "Candidate staking/points specs from established protocols."),
    ("Source Verification Agent", "verifier", "Independent confirming source URLs attached as positive evidence."),
    ("Scam Detection Agent", "verifier", "Scam-report URLs attached as negative evidence — the org's standing red team."),
    ("Opportunity Ranking Agent", "analyst", "A reward-potential proposal (0-40, clamped) plus an evidence-cited narrative."),
    ("Debate: Advocate", "debate", "The strongest honest case FOR each verified opportunity — transcript only."),
    ("Debate: Skeptic", "debate", "The danger case; its only teeth are scam reports the gate counts."),
    ("Debate: Strategist", "debate", "The fit case against the user's profile — transcript only."),
    ("Portfolio Strategy Agent", "strategy", "A voiced strategy note over the deterministically selected mission."),
]

# (name, determinism, about) — the scaffold gate's checks, mirrored from
# crypto-hunter/engine/gate.py. All HARD; the gate fails closed.
_GATES: list[tuple[str, str, str]] = [
    ("scaffold:known_scam_list", "hard", "any source domain on the curated scam list is a hard fail — taint is a red flag, not evidence"),
    ("scaffold:official_domain_allowlist", "hard", "at least one source on the official/aggregator allowlist (subdomain-aware)"),
    ("scaffold:source_validity", "hard", "per-source validity: official, or RDAP-aged past the floor; invalid sources are excluded, never decisive"),
    ("scaffold:multi_source_confirmation", "hard", "enough VALID domains confirm (official presence suffices); more evidence can only help"),
    ("scaffold:contract_verified", "hard", "a claimed contract must be source-verified on an explorer; unverifiable fails closed"),
    ("scaffold:scam_report_evidence", "hard", "one credible scam report is a hard fail; unresolved reports fail closed (an outage cannot disarm the skeptic); reports follow the opportunity across name variants"),
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
