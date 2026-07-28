from collector.explain import CHECK_EXPLANATIONS, explain_check


def test_explain_check_returns_known_explanation() -> None:
    assert "scam list" in explain_check("known_scam_list").lower()


def test_explain_check_falls_back_gracefully_for_an_unknown_check() -> None:
    """A future source kind's own check name must never blank the UI —
    same graceful-degradation posture as the rest of the collector."""
    result = explain_check("some_future_check_nobody_registered_yet")
    assert result  # non-empty
    assert "some_future_check" not in result  # a real fallback sentence, not an echo


def test_every_hunter_engine_gate_check_has_an_explanation() -> None:
    """The six checks every Hunter engine's gate produces (see orgs/*/roster.py)
    must all be covered — a missing one would silently fall back to the
    generic text for real, everyday collected records."""
    for check in (
        "known_scam_list", "official_domain_allowlist", "source_validity",
        "multi_source_confirmation", "contract_verified", "scam_report_evidence",
    ):
        assert check in CHECK_EXPLANATIONS
