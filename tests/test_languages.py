"""P15a — the Language seam: the same verification model, two languages.

The org verifies by executing code and checking it. These tests prove that holds in Python
AND JavaScript through one interface: cases run, oracle-free properties bite mutants, and
syntax/definedness is checked — in both languages, with no model involved. Adding a language
means making these pass for it; the engine never changes.
"""

from __future__ import annotations

import pytest

from engine.executor import LocalSubprocessExecutor
from orgs.software_studio.languages import LANGUAGES
from orgs.software_studio.properties import parse_properties

EXEC = LocalSubprocessExecutor()

FIX = {
    "python": {
        "double": "def double(x):\n    return x * 2\n",
        "double_add": "def double(x):\n    return x + 2\n",
        "double_neg": "def double(x):\n    return -x * 2\n",
        "codec": "def enc(x):\n    return x + 100\n\ndef dec(y):\n    return y - 100\n",
        "codec_bad": "def enc(x):\n    return x + 100\n\ndef dec(y):\n    return y - 99\n",
        "mysort": "def mysort(xs):\n    return sorted(xs)\n",
        "mysort_drop": "def mysort(xs):\n    return sorted(xs)[1:]\n",
        "rev": "def rev(s):\n    return s[::-1]\n",
        "rev_bad": "def rev(s):\n    return s + '!'\n",
        "no_fn": "def other(x):\n    return x\n",
    },
    "javascript": {
        "double": "function double(x){ return x * 2; }\n",
        "double_add": "function double(x){ return x + 2; }\n",
        "double_neg": "function double(x){ return -x * 2; }\n",
        "codec": "function enc(x){ return x + 100; }\nfunction dec(y){ return y - 100; }\n",
        "codec_bad": "function enc(x){ return x + 100; }\nfunction dec(y){ return y - 99; }\n",
        "mysort": "function mysort(xs){ return [...xs].sort((a,b)=>a-b); }\n",
        "mysort_drop": "function mysort(xs){ return [...xs].sort((a,b)=>a-b).slice(1); }\n",
        "rev": "function rev(s){ return s.split('').reverse().join(''); }\n",
        "rev_bad": "function rev(s){ return s + '!'; }\n",
        "no_fn": "function other(x){ return x; }\n",
    },
}

CASES = [{"args": [5], "expected": 10}, {"args": [-3], "expected": -6}]
LANGS = ["python", "javascript"]


@pytest.mark.parametrize("lang", LANGS)
def test_cases_pass_for_good_code_and_fail_for_wrong(lang):
    L, f = LANGUAGES[lang], FIX[lang]
    assert L.run_cases(EXEC, f["double"], "double", CASES)[0]
    ok, ev = L.run_cases(EXEC, f["double_add"], "double", CASES)
    assert not ok and "case" in ev


@pytest.mark.parametrize("lang", LANGS)
def test_syntax_and_definedness(lang):
    L, f = LANGUAGES[lang], FIX[lang]
    assert L.syntax_ok(EXEC, f["double"], "double")[0]
    ok, ev = L.syntax_ok(EXEC, f["no_fn"], "double")
    assert not ok  # double() not defined


@pytest.mark.parametrize("lang", LANGS)
def test_monotonic_property_bites(lang):
    L, f = LANGUAGES[lang], FIX[lang]
    props = parse_properties([{"kind": "monotonic", "direction": "increasing", "inputs": [[1], [2], [3]]}])
    assert L.run_properties(EXEC, f["double"], "double", props)[0]
    ok, ev = L.run_properties(EXEC, f["double_neg"], "double", props)
    assert not ok and "monotonic" in ev


@pytest.mark.parametrize("lang", LANGS)
def test_round_trip_property_bites(lang):
    L, f = LANGUAGES[lang], FIX[lang]
    props = parse_properties([{"kind": "round_trip", "inverse": "dec", "inputs": [[5], [0], [42]]}])
    assert L.run_properties(EXEC, f["codec"], "enc", props)[0]
    ok, ev = L.run_properties(EXEC, f["codec_bad"], "enc", props)
    assert not ok and "round_trip" in ev


@pytest.mark.parametrize("lang", LANGS)
def test_involution_property_bites(lang):
    L, f = LANGUAGES[lang], FIX[lang]
    props = parse_properties([{"kind": "involution", "inputs": [["abc"], ["xy"]]}])
    assert L.run_properties(EXEC, f["rev"], "rev", props)[0]
    ok, ev = L.run_properties(EXEC, f["rev_bad"], "rev", props)
    assert not ok and "involution" in ev


@pytest.mark.parametrize("lang", LANGS)
def test_invariant_property_bites(lang):
    L, f = LANGUAGES[lang], FIX[lang]
    props = parse_properties([
        {"kind": "invariant", "invariant": "sorted_ascending", "inputs": [[[3, 1, 2]]]},
        {"kind": "invariant", "invariant": "is_permutation_of_input", "inputs": [[[3, 1, 2]]]},
    ])
    assert L.run_properties(EXEC, f["mysort"], "mysort", props)[0]
    ok, ev = L.run_properties(EXEC, f["mysort_drop"], "mysort", props)
    assert not ok and "is_permutation_of_input" in ev
