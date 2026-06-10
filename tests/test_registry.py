"""The org registry — both orgs behind one interface, picked by name.

Proves the Hub-facing claim: an org is an entry in a catalog, and running one is
`get_org(name).build(goal, provider, memory)` regardless of domain. The normalized
OrgRun is what makes the Hub org-agnostic.
"""

from __future__ import annotations

import json

import pytest

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from orgs.registry import REGISTRY, get_org

SOFTWARE_SPEC = json.dumps(
    {
        "function_name": "add",
        "description": "add two numbers",
        "signature": "def add(a, b)",
        "cases": [{"args": [1, 2], "expected": 3}],
    }
)
DOCS_OUTLINE = json.dumps(
    {"title": "List comprehensions", "sections": ["What they are", "Example"], "min_examples": 1}
)
DOC = (
    "# List comprehensions\n\n## What they are\nA compact way to build lists from "
    "iterables in one readable expression instead of an explicit loop.\n\n## Example\n"
    "```python\nassert [x * x for x in range(3)] == [0, 1, 4]\n```\n"
)

PROVIDER = ScriptedProvider(
    {
        "spec": SOFTWARE_SPEC,
        "developer": "def add(a, b):\n    return a + b\n",
        "qa": "[]",
        "outline": DOCS_OUTLINE,
        "writer": DOC,
    }
)


def test_registry_lists_both_orgs():
    assert set(REGISTRY) == {"software", "docs"}
    for org in REGISTRY.values():
        assert org.title and org.description and org.goal_hint
        assert org.input_noun and org.produces and org.verified_by


def test_unknown_org_raises_with_known_names():
    with pytest.raises(KeyError, match="docs"):
        get_org("research")


def test_software_runs_through_registry(tmp_path):
    run = get_org("software").build("add two numbers", PROVIDER, MemoryStore(tmp_path))
    assert run.org == "software" and run.accepted
    assert [o.artifact.type for o in run.outcomes] == ["spec", "code"]
    assert run.run_id and run.activity


def test_docs_runs_through_registry(tmp_path):
    run = get_org("docs").build("list comprehensions", PROVIDER, MemoryStore(tmp_path))
    assert run.org == "docs" and run.accepted
    assert [o.artifact.type for o in run.outcomes] == ["docs-outline", "document"]


def test_rejected_early_run_has_single_outcome(tmp_path):
    provider = ScriptedProvider({"spec": "just prose, no JSON", "developer": "", "qa": "[]"})
    run = get_org("software").build("x", provider, MemoryStore(tmp_path))
    assert not run.accepted
    assert len(run.outcomes) == 1  # the rejected spec; the developer never ran
