"""P13d — the voting oracle and ConsensusGate: graded confidence, never a hard verdict.

The oracle re-derives an expected value across independent draws and reports how strongly
they agreed. ConsensusGate uses it to flag code that disagrees with the consensus — for the
value gap (a+b vs a-b) that oracle-free properties can't reach — but it is always SOFT.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ModelProvider, ScriptedProvider, SequencedProvider
from orgs.software_studio.gates import ConsensusGate
from orgs.software_studio.oracle import VoteResult, VotingOracle, parse_value
from orgs.software_studio.pipeline import build_software
from orgs.software_studio.spec import parse_spec


def _val(x: object) -> str:
    return json.dumps({"value": x})


# --- the oracle: parsing + tallying ----------------------------------------------


def test_parse_value():
    assert parse_value('{"value": 5}') == (True, 5)
    assert parse_value("the answer is {\"value\": 7} ok") == (True, 7)
    assert parse_value("no json here") == (False, None)
    assert parse_value('{"result": 5}') == (False, None)


def test_unanimous_draws_are_high_confidence():
    # one provider sampled 3x, all agree on 5
    oracle = VotingOracle([SequencedProvider({"oracle": [_val(5), _val(5), _val(5)]})], samples=3)
    r = oracle.vote(function_name="add", description="add two numbers", args=[2, 3])
    assert r.consensus == 5 and r.agreement == 1.0 and r.total == 3
    assert r.confidence() == "high"


def test_split_draws_lower_confidence():
    oracle = VotingOracle([SequencedProvider({"oracle": [_val(5), _val(5), _val(6)]})], samples=3)
    r = oracle.vote(function_name="add", description="add", args=[2, 3])
    assert r.consensus == 5 and abs(r.agreement - 2 / 3) < 1e-9 and r.total == 3
    assert r.confidence() == "moderate"


def test_multiple_models_vote():
    # three independent providers (different "models"), two agree
    oracle = VotingOracle(
        [ScriptedProvider({"oracle": _val(5)}),
         ScriptedProvider({"oracle": _val(5)}),
         ScriptedProvider({"oracle": _val(9)})],
        samples=1,
    )
    r = oracle.vote(function_name="add", description="add", args=[2, 3])
    assert r.consensus == 5 and r.total == 3 and abs(r.agreement - 2 / 3) < 1e-9


def test_no_valid_draws_is_no_confidence():
    oracle = VotingOracle([ScriptedProvider({"oracle": "sorry, can't help"})], samples=1)
    r = oracle.vote(function_name="add", description="add", args=[2, 3])
    assert r.total == 0 and r.consensus is None and r.confidence() == "none"


def test_float_consensus_uses_isclose():
    oracle = VotingOracle([SequencedProvider({"oracle": [_val(37.77777778), _val(37.77777778)]})], samples=2)
    r = oracle.vote(function_name="c2f", description="celsius to fahrenheit", args=[0])
    assert r.agreement == 1.0 and r.total == 2


# --- ConsensusGate: SOFT graded confidence ---------------------------------------

ADD_SPEC = json.dumps(
    {"function_name": "add", "description": "add two numbers", "signature": "def add(a, b)",
     "cases": [{"args": [2, 3], "expected": 5}, {"args": [10, 1], "expected": 11}]}
)
GOOD = "def add(a, b):\n    return a + b\n"
WRONG = "def add(a, b):\n    return a - b\n"  # no oracle-free property pins this


def _spec():
    return parse_spec(ADD_SPEC)


def _oracle(values: list[object]) -> VotingOracle:
    # one provider that returns the right answer for each input, sampled 3x per input
    return VotingOracle([SequencedProvider({"oracle": [_val(v) for v in values]})], samples=3)


def test_consensus_gate_confirms_correct_code_with_high_confidence():
    # 2 inputs x 3 samples = 6 draws: 5,5,5 then 11,11,11
    gate = ConsensusGate(_spec(), _oracle([5, 5, 5, 11, 11, 11]))
    art = type("A", (), {"payload": GOOD})()
    res = gate.check(art)  # type: ignore[arg-type]
    assert res.passed and res.determinism.value == "soft"
    assert "high" in res.evidence


def test_consensus_gate_flags_wrong_code_as_advisory_not_a_block():
    gate = ConsensusGate(_spec(), _oracle([5, 5, 5, 11, 11, 11]))
    art = type("A", (), {"payload": WRONG})()
    res = gate.check(art)  # type: ignore[arg-type]
    assert not res.passed and res.determinism.value == "soft"  # advisory, never hard
    assert "disagrees" in res.evidence and "consensus" in res.evidence


def test_wrong_code_with_consensus_oracle_ships_but_is_flagged(tmp_path):
    # End to end: WRONG add has no oracle-free property to hard-catch it, so the build still
    # SHIPS on the structural hard gates — but the consensus vote records a strong soft flag.
    class P(ModelProvider):
        def propose(self, *, role, prompt, system=None):
            if role == "spec":
                return ADD_SPEC
            if role == "qa":
                return "[]"
            if role == "oracle":
                return _val(5) if '[2, 3]' in prompt or '"args"' not in prompt else _val(11)
            if role == "developer":
                return WRONG
            raise KeyError(role)

    oracle = VotingOracle([P()], samples=1)
    result = build_software("add two numbers", P(), MemoryStore(tmp_path), oracle=oracle)
    assert result.accepted  # honest limit: no hard gate catches a pure value error here
    assert result.code_outcome is not None
    consensus = next(
        g for g in result.code_outcome.artifact.provenance.gate_results if g.gate_name == "consensus"
    )
    assert consensus.determinism.value == "soft" and not consensus.passed
