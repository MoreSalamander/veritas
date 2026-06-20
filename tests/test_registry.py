"""The org registry — orgs behind one interface, picked by name.

Proves the Hub-facing claim: an org is an entry in a catalog, and running one is
`get_org(name).build(goal, provider, memory)`. The normalized OrgRun is what makes
the Hub org-agnostic. (Only the software org is registered: documenting code is a
role in it, not a peer org, because docs are verified the same way code is.)
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
DOC = "# add\n\nAdds two numbers.\n\n```python\nassert add(2, 3) == 5\nprint(add(10, 20))\n```\n"

PROVIDER = ScriptedProvider(
    {
        "spec": SOFTWARE_SPEC,
        "developer": "def add(a, b):\n    return a + b\n",
        "qa": "[]",
        "doc": DOC,
    }
)


def test_registry_lists_orgs():
    assert set(REGISTRY) == {"software", "web", "research", "production", "empirical"}  # five verification models
    for org in REGISTRY.values():
        assert org.title and org.description and org.goal_hint
        assert org.input_noun and org.produces and org.verified_by


def test_unknown_org_raises_with_known_names():
    with pytest.raises(KeyError, match="software"):
        get_org("biology")


def test_software_runs_through_registry_and_documents(tmp_path):
    # The registry runs software with document=True, so the doc role is part of the run.
    run = get_org("software").build("add two numbers", PROVIDER, MemoryStore(tmp_path))
    assert run.org == "software" and run.accepted
    assert [o.artifact.type for o in run.outcomes] == ["spec", "code", "documentation"]
    assert run.run_id and run.activity


def test_rejected_early_run_has_single_outcome(tmp_path):
    provider = ScriptedProvider({"spec": "just prose, no JSON", "developer": "", "qa": "[]"})
    run = get_org("software").build("x", provider, MemoryStore(tmp_path))
    assert not run.accepted
    assert len(run.outcomes) == 1  # the rejected spec; the developer never ran
