"""P15b — a goal builds and verifies in any language end to end.

The spec is language-agnostic; the Language changes only what code is asked for and how it's
checked. Proven offline: the SAME spec ships a verified function in JavaScript and in Python
through one pipeline, and a wrong implementation is rejected by the oracle-free property gate
in the target language.
"""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.software_studio.languages import LANGUAGES
from orgs.software_studio.pipeline import build_function_in

SPEC = json.dumps(
    {"function_name": "double", "description": "doubles a number", "signature": "double(x)",
     "cases": [{"args": [5], "expected": 10}, {"args": [-3], "expected": -6}],
     "properties": [{"kind": "monotonic", "direction": "increasing", "inputs": [[1], [2], [3]]}]}
)
JS_GOOD = "function double(x){ return x * 2; }\n"
JS_WRONG = "function double(x){ return -x * 2; }\n"  # breaks monotonic
PY_GOOD = "def double(x):\n    return x * 2\n"


def test_js_function_builds_and_verifies_end_to_end(tmp_path):
    res = build_function_in(LANGUAGES["javascript"], "double a number",
                            ScriptedProvider({"spec": SPEC, "developer": JS_GOOD}), MemoryStore(tmp_path))
    assert res.accepted
    assert res.code_outcome is not None
    names = [g.gate_name for g in res.code_outcome.artifact.provenance.gate_results]
    assert names == ["syntax", "properties", "acceptance-tests", "validation"]
    assert res.code_outcome.memory_path.parent.name == "institutional"


def test_js_wrong_code_rejected_by_property_gate(tmp_path):
    res = build_function_in(LANGUAGES["javascript"], "double",
                            ScriptedProvider({"spec": SPEC, "developer": JS_WRONG}), MemoryStore(tmp_path))
    assert not res.accepted
    prop = next(g for g in res.code_outcome.artifact.provenance.gate_results if g.gate_name == "properties")
    assert not prop.passed and "monotonic" in prop.evidence


def test_python_builds_through_the_same_generic_pipeline(tmp_path):
    res = build_function_in(LANGUAGES["python"], "double",
                            ScriptedProvider({"spec": SPEC, "developer": PY_GOOD}), MemoryStore(tmp_path))
    assert res.accepted  # one pipeline, both languages
