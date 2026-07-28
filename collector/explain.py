"""Plain-English explanations for the structural checks that show up in a
collected record's `verification` list — the Collector's own version of the
"Explain it to me" treatment every Hunter engine already gives its own gate
checks (see orgs/*/roster.py's `_GATES` descriptions, which this mirrors).

One canonical text per check, not copy-pasted per engine: the six
hunter_engine checks are literally the same shared code
(hunter_engine.gate.Gate) regardless of which Hunter engine ran it, so one
description covers all three.
"""

from __future__ import annotations

CHECK_EXPLANATIONS: dict[str, str] = {
    "known_scam_list": (
        "Any source domain on the curated scam list is a hard fail — taint is a red flag, "
        "not evidence."
    ),
    "official_domain_allowlist": (
        "At least one source must be on the official/aggregator allowlist (subdomain-aware)."
    ),
    "source_validity": (
        "Each source must be official, or RDAP-aged past the floor; invalid sources are "
        "excluded from consideration, never decisive."
    ),
    "multi_source_confirmation": (
        "Enough independently-valid domains must confirm the same claim (an official source "
        "alone suffices); more evidence can only help, never hurt."
    ),
    "contract_verified": (
        "A claimed on-chain contract must be source-verified on a block explorer; "
        "unverifiable fails closed. Not applicable — and passes trivially — when no "
        "on-chain claim is made at all."
    ),
    "scam_report_evidence": (
        "One credible scam report is a hard fail; unresolved reports fail closed (an outage "
        "can't disarm the skeptic), and reports follow the opportunity across name variants."
    ),
    "allocation-item-shape": (
        "Confirms this allocation item actually carries the engine name and opportunity id "
        "that Opportunity's own allocation process guarantees — not a re-check of the "
        "underlying opportunity's own truth, just that the record has the shape it's "
        "supposed to have."
    ),
}

_FALLBACK = "A structural check performed by the source's own deterministic gate."


def explain_check(check: str) -> str:
    return CHECK_EXPLANATIONS.get(check, _FALLBACK)
