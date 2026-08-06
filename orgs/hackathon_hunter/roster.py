"""The hackathon-hunter org's roster, as structured data for the front door's
Org view.

Unlike the in-repo studios, this cast and these gates live in the org's own
codebase (~/MoreSalamander/hackathon-hunter). The descriptions are authored
here; the cast mirrors that repo's own engine/roster.py, and the checks
mirror the shared hunter_engine.gate.Gate every Hunter engine uses plus this
domain's four extra checks — HARD, fail-closed, the only path to a trusted
record. The fourth engine of the family, created inside the DataHub
hackathon window and DataHub-native from its first commit.
"""

from __future__ import annotations

from typing import Any

# (display name, role, what it produces) — proposers; they decide nothing.
_CAST: list[tuple[str, str, str]] = [
    ("Devpost Listings Scout", "scout", "Candidate specs from Devpost's open-hackathon listings — untrusted by construction."),
    ("MLH Season Scout", "scout", "Candidate specs from MLH's season calendar, student-eligibility noted."),
    ("Source Verification Agent", "verifier", "A second independent confirmation: organizer site, sponsor announcement, or platform rules page."),
    ("Scam Detection Agent", "verifier", "Hunts fake-prize, pay-to-enter, and lookalike-platform reports — the org's standing red team."),
    ("Opportunity Ranking Agent", "analyst", "A prize-vs-effort proposal (0-40, clamped) plus an evidence-cited narrative."),
    ("Debate: Advocate", "debate", "The strongest honest case FOR entering — transcript only."),
    ("Debate: Skeptic", "debate", "The effort-vs-odds case against sponsor-judged subjectivity — transcript only."),
    ("Debate: Strategist", "debate", "The fit case: themes vs skills, team size, time budget — transcript only."),
    ("Portfolio Strategy Agent", "strategy", "A voiced strategy note over the deterministically selected mission."),
    ("Explainer", "coach", "Translates platform and rules jargon into plain English."),
]

# (name, determinism, about) — the shared hunter_engine.gate.Gate checks plus
# this domain's own four. All HARD; the gate fails closed.
_GATES: list[tuple[str, str, str]] = [
    ("scaffold:known_scam_list", "hard", "any source domain on the curated scam list is a hard fail — taint is a red flag, not evidence"),
    ("scaffold:official_domain_allowlist", "hard", "at least one source on the official platform allowlist — devpost.com / mlh.io (subdomain-aware)"),
    ("scaffold:source_validity", "hard", "per-source validity: official, or RDAP-aged past the floor; invalid sources are excluded, never decisive"),
    ("scaffold:multi_source_confirmation", "hard", "enough VALID domains confirm (official presence suffices); more evidence can only help"),
    ("scaffold:scam_report_evidence", "hard", "one credible fake-prize or impersonation report is a hard fail; unresolved reports fail closed"),
    ("domain:official_listing_confirmed", "hard", "the candidate's OWN source is the platform's listing — a lookalike 'prize portal' never counts"),
    ("domain:deadline_is_future", "hard", "a parseable submission deadline that hasn't passed; an event you can't enter isn't an opportunity"),
    ("domain:prize_documented", "hard", "a real documented prize pool; 'exposure' doesn't gate"),
    ("domain:eligibility_parseable", "hard", "the rules must say who may enter, or fit can't be checked against the profile"),
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
        "center. Born inside the DataHub hackathon window, DataHub-native from its first "
        "commit — every verdict it records is governed metadata, not a log line.",
    }
