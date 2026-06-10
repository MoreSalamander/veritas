"""Phase 2 definition-of-done — the full cast reviews the code.

The code artifact carries the whole cast's verdicts in one provenance trail. Proven
offline: a clean build collects five gate verdicts and Validation's approval; the
security scan hard-rejects working-but-dangerous code; a QA discrepancy is recorded
as an advisory finding without blocking; Validation withholds when a hard gate fails.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.software_studio.pipeline import build_software

GOOD_SPEC = json.dumps(
    {
        "function_name": "add",
        "description": "add two numbers",
        "signature": "def add(a, b)",
        "cases": [
            {"args": [1, 2], "expected": 3},
            {"args": [5, 5], "expected": 10},
            {"args": [-1, 1], "expected": 0},
        ],
    }
)
GOOD_CODE = "def add(a, b):\n    return a + b\n"
GOOD_QA = json.dumps([{"args": [0, 0], "expected": 0}, {"args": [100, -100], "expected": 0}])
# Works correctly, but uses eval — the security scan must reject it.
INSECURE_CODE = "def add(a, b):\n    return eval(f'{a}+{b}')\n"
# QA's expected values are wrong (a bad oracle) — must be advisory, not a block.
WRONG_QA = json.dumps([{"args": [1, 1], "expected": 99}])


def _provider(spec: str, code: str, qa: str) -> ScriptedProvider:
    return ScriptedProvider({"spec": spec, "developer": code, "qa": qa})


def test_clean_build_collects_full_cast_provenance(tmp_path):
    result = build_software("add two numbers", _provider(GOOD_SPEC, GOOD_CODE, GOOD_QA),
                            MemoryStore(tmp_path))
    assert result.accepted
    assert result.code_outcome is not None
    gate_names = [g.gate_name for g in result.code_outcome.artifact.provenance.gate_results]
    assert gate_names == ["syntax", "acceptance-tests", "security-scan", "qa-review", "validation"]
    assert result.code_outcome.memory_path.parent.name == "institutional"
    # Validation is the final authority and it approved.
    validation = result.code_outcome.artifact.provenance.gate_results[-1]
    assert validation.gate_name == "validation" and validation.passed


def test_security_rejects_working_but_dangerous_code(tmp_path):
    result = build_software("add", _provider(GOOD_SPEC, INSECURE_CODE, GOOD_QA),
                            MemoryStore(tmp_path))
    assert not result.accepted  # it passes the cases, but eval is rejected
    assert result.code_outcome is not None
    assert result.code_outcome.memory_path.parent.name == "failures"
    security = next(
        g for g in result.code_outcome.artifact.provenance.gate_results if g.gate_name == "security-scan"
    )
    assert not security.passed and "eval()" in security.evidence
    # Validation must withhold when a hard gate failed.
    validation = result.code_outcome.artifact.provenance.gate_results[-1]
    assert not validation.passed and "withheld" in validation.evidence


def test_qa_discrepancy_is_advisory_not_a_block(tmp_path):
    result = build_software("add", _provider(GOOD_SPEC, GOOD_CODE, WRONG_QA),
                            MemoryStore(tmp_path))
    assert result.accepted  # the hard gates all passed
    assert result.code_outcome is not None
    qa = next(
        g for g in result.code_outcome.artifact.provenance.gate_results if g.gate_name == "qa-review"
    )
    assert qa.determinism.value == "soft" and not qa.passed
    assert "soft findings noted" in (result.code_outcome.artifact.provenance.accepted_because or "")


def test_unparseable_qa_yields_no_findings(tmp_path):
    result = build_software("add", _provider(GOOD_SPEC, GOOD_CODE, "sorry, I can't help with that"),
                            MemoryStore(tmp_path))
    assert result.accepted
    assert result.code_outcome is not None
    qa = next(
        g for g in result.code_outcome.artifact.provenance.gate_results if g.gate_name == "qa-review"
    )
    assert qa.passed and "no usable" in qa.evidence
