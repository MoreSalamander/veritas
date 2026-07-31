"""orgs/datahub_emit.py — offline, deterministic (no live DataHub needed).

The live emit path (emit_org_run's actual REST calls) is exercised
manually against a running `datahub docker quickstart`, not here — same
split as hub/ingest.py's YtDlpFetcher. What's covered here is everything
that doesn't need a network: URN construction, the Determinism -> tag
mapping, timestamp conversion, and the toy OrgRun builder's structure.

Run with .venv-datahub, not the repo's main .venv — see the importorskip
reason below.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "datahub",
    reason="acryl-datahub needs Python 3.12 here (pydantic-core has no 3.14 wheel yet) — "
    "run this file with .venv-datahub, not the repo's main .venv",
)

from engine.artifact import Determinism, GateResult
from engine.run import Outcome
from orgs.datahub_emit import (
    _millis,
    _org_urn,
    _outcome_urn,
    _owner_urn,
    _rigor_determinism,
    build_toy_org_run,
)


def test_org_and_outcome_urns_are_scoped_to_the_veritas_platform():
    run = build_toy_org_run("hunter-demo", "run01", num_outcomes=1)
    assert _org_urn(run) == "urn:li:dataset:(urn:li:dataPlatform:veritas,hunter-demo-run01,PROD)"
    assert _outcome_urn(run, 0) == (
        "urn:li:dataset:(urn:li:dataPlatform:veritas,hunter-demo-run01-outcome-0,PROD)"
    )


def test_owner_urn_is_a_corpgroup_not_a_corpuser():
    run = build_toy_org_run("crypto_hunter", "run02", num_outcomes=1)
    assert _owner_urn(run) == "urn:li:corpGroup:veritas-crypto-hunter"


def test_rigor_determinism_prefers_human_over_hard_over_soft():
    def outcome_with(*determinisms: Determinism) -> Outcome:
        gate_results = [
            GateResult(gate_name="g", determinism=d, passed=True, evidence="")
            for d in determinisms
        ]
        return Outcome(artifact=None, accepted=True, gate_results=gate_results, memory_path=None)  # type: ignore[arg-type]

    assert _rigor_determinism(outcome_with(Determinism.SOFT)) == Determinism.SOFT
    assert _rigor_determinism(outcome_with(Determinism.HARD, Determinism.SOFT)) == Determinism.HARD
    assert _rigor_determinism(outcome_with(Determinism.HARD, Determinism.HUMAN)) == Determinism.HUMAN
    assert _rigor_determinism(outcome_with()) is None


def test_millis_parses_iso_timestamp():
    assert _millis("2026-01-01T00:00:00+00:00") == 1767225600000


def test_build_toy_org_run_produces_the_requested_outcome_count():
    run = build_toy_org_run("hunter-demo", "run03", num_outcomes=7)
    assert run.org == "hunter-demo"
    assert run.run_id == "run03"
    assert len(run.outcomes) == 7
    # every outcome carries exactly one gate result, real Artifact/GateResult
    # types, and an accepted status consistent with its own gate's verdict
    for outcome in run.outcomes:
        assert len(outcome.gate_results) == 1
        assert outcome.accepted == outcome.gate_results[0].passed
        assert outcome.accepted == (outcome.artifact.status.value == "accepted")
