"""P7 — one front door routes function vs module; the hub rides on it."""

from __future__ import annotations

import json

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.software_studio.builder import build

SPEC = json.dumps(
    {"function_name": "add", "description": "add", "signature": "def add(a, b)",
     "cases": [{"args": [1, 2], "expected": 3}]}
)
CODE = "def add(a, b):\n    return a + b\n"
DOC = "# add\n\n```python\nassert add(2, 3) == 5\n```\n"

CONTRACT = json.dumps(
    {"module_name": "temp", "functions": [
        {"function_name": "c2f", "signature": "def c2f(c)", "cases": [{"args": [0], "expected": 32}]},
        {"function_name": "f2c", "signature": "def f2c(f)", "cases": [{"args": [32], "expected": 0}]},
    ]}
)
PM = json.dumps(["assert abs(f2c(c2f(100)) - 100) < 1e-9"])
MODULE = "def c2f(c):\n    return c * 9 / 5 + 32\n\ndef f2c(f):\n    return (f - 32) * 5 / 9\n"


def test_routes_to_function_and_documents(tmp_path):
    provider = ScriptedProvider({"router": "function", "spec": SPEC, "developer": CODE, "qa": "[]", "doc": DOC})
    result = build("add two numbers", provider, MemoryStore(tmp_path))
    assert result.shape == "function" and result.accepted
    assert [o.artifact.type for o in result.outcomes] == ["spec", "code", "documentation"]


def test_routes_to_module(tmp_path):
    provider = ScriptedProvider({"router": "module", "architect": CONTRACT, "pm": PM, "developer": MODULE})
    result = build("a temperature module", provider, MemoryStore(tmp_path))
    assert result.shape == "module" and result.accepted
    assert [o.artifact.type for o in result.outcomes] == ["contract", "integration-spec", "module-code"]


def test_router_defaults_to_function_when_unavailable(tmp_path):
    # No "router" role -> classify falls back to the simpler shape, build still works.
    provider = ScriptedProvider({"spec": SPEC, "developer": CODE, "qa": "[]", "doc": DOC})
    result = build("add", provider, MemoryStore(tmp_path))
    assert result.shape == "function" and result.accepted


def test_explicit_shape_overrides_router(tmp_path):
    provider = ScriptedProvider({"architect": CONTRACT, "pm": PM, "developer": MODULE})
    result = build("anything", provider, MemoryStore(tmp_path), shape="module")
    assert result.shape == "module" and result.accepted
