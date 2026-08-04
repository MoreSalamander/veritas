"""The tutorial-dispense endpoints (Knowledge Graph source -> lesson -> a real container), over
the HTTP control plane. Veritas persists its own copy the moment the gate passes; mirroring into
myAIstro is best-effort and must never block or hide a product Veritas already has.

`build_tutorial_image`/`dispense_copy`/`return_copy`/`publish_tutorial` are monkeypatched to fast
stubs throughout — this suite proves the Hub's own plumbing (token issuance, background worker,
native persistence, gate honesty, retry, the dispense/return HTTP surface), not Docker or
myAIstro's write path. The real, slow, Docker-backed path is test_tutorial_container.py's job
(skipped there without a daemon; never silently exercised here).
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider, SequencedProvider
from hub.app import create_app
from hub.tutorial_container import DispensedCopy

GOOD_CONTENT = json.dumps({
    "overview": "A short walkthrough.",
    "materials": ["one widget"],
    "sections": [{"title": "Assemble", "steps": [{"instruction": "Attach the widget."}]}],
    "reference": [],
})


def _client(tmp_path, provider, monkeypatch, *, build_ok: bool = True):
    if build_ok:
        monkeypatch.setattr(
            "hub.app.build_tutorial_image",
            lambda product_id, title, content, url, channel: f"veritas-tutorial-{product_id}:local",
        )
    else:
        def _boom(product_id, title, content, url, channel):
            raise RuntimeError("no docker daemon")
        monkeypatch.setattr("hub.app.build_tutorial_image", _boom)
    monkeypatch.setattr(
        "hub.app.publish_tutorial",
        lambda source, content, spec: {"status": "written", "entries": 1},
    )
    return TestClient(create_app(data_dir=tmp_path, provider=provider))


def _seed_source(client) -> str:
    resp = client.post(
        "/api/commons",
        json={
            "url": "https://youtu.be/abc123",
            "channel": "Some Channel",
            "transcript": "A talk about widgets.",
            "captured_why": "for a tutorial",
        },
    )
    return str(resp.json()["id"])


def _poll(client, token: str) -> dict:
    for _ in range(200):
        state = client.get(f"/api/tutorial/progress/{token}").json()
        if state.get("done"):
            return state
        time.sleep(0.01)
    raise AssertionError("tutorial worker never finished")


def test_a_passing_gate_persists_a_product_and_builds_its_container(tmp_path, monkeypatch):
    client = _client(tmp_path, ScriptedProvider({"tutorial-generator": GOOD_CONTENT}), monkeypatch)
    source_id = _seed_source(client)

    started = client.post("/api/tutorial/start", json={"source_id": source_id})
    assert started.status_code == 200
    token = started.json()["token"]

    state = _poll(client, token)
    assert state["passed"] is True
    assert state["error"] is None
    assert state["product_id"]  # Veritas's own record id, independent of the mirror
    assert state["container_image"] == f"veritas-tutorial-{state['product_id']}:local"
    assert state["mirror"] == {"status": "written", "entries": 1}

    products = client.get("/api/tutorial/products").json()
    assert len(products) == 1
    assert products[0]["id"] == state["product_id"]
    assert products[0]["overview"] == "A short walkthrough."
    assert products[0]["container_image"] == state["container_image"]


def test_a_failed_container_build_does_not_block_the_product(tmp_path, monkeypatch):
    # No docker daemon, a build error, whatever — the gated content still becomes a real,
    # listable Veritas product; it just has nothing to dispense yet.
    client = _client(
        tmp_path, ScriptedProvider({"tutorial-generator": GOOD_CONTENT}), monkeypatch, build_ok=False,
    )
    source_id = _seed_source(client)

    started = client.post("/api/tutorial/start", json={"source_id": source_id})
    state = _poll(client, started.json()["token"])

    assert state["passed"] is True
    assert state["product_id"]
    assert state["container_image"] is None

    products = client.get("/api/tutorial/products").json()
    assert len(products) == 1
    assert products[0]["container_image"] is None


def test_a_failed_mirror_does_not_erase_the_native_product(tmp_path, monkeypatch):
    # myAIstro (or any other downstream extension) being unreachable must never hide a product
    # Veritas already gated and persisted itself — the vault-sync contract, applied here.
    client = _client(tmp_path, ScriptedProvider({"tutorial-generator": GOOD_CONTENT}), monkeypatch)

    def _boom(source, content, spec):
        raise RuntimeError("myAIstro backend unreachable")
    monkeypatch.setattr("hub.app.publish_tutorial", _boom)

    source_id = _seed_source(client)
    started = client.post("/api/tutorial/start", json={"source_id": source_id})
    state = _poll(client, started.json()["token"])

    assert state["passed"] is True
    assert state["product_id"]
    assert state["mirror"]["status"] == "mirror_failed"

    products = client.get("/api/tutorial/products").json()
    assert len(products) == 1


def test_unknown_source_id_is_a_404(tmp_path, monkeypatch):
    client = _client(tmp_path, ScriptedProvider({}), monkeypatch)
    resp = client.post("/api/tutorial/start", json={"source_id": "mem_nope"})
    assert resp.status_code == 404


def test_a_persistently_bad_proposal_is_rejected_not_persisted(tmp_path, monkeypatch):
    # Every attempt returns unusable prose (no JSON) — the gate must fail every one of the
    # bounded retries and nothing may reach Veritas's own store, a container, or the mirror.
    build_called = {"yes": False}
    client = _client(tmp_path, ScriptedProvider({"tutorial-generator": "not json at all"}), monkeypatch)
    monkeypatch.setattr(
        "hub.app.build_tutorial_image",
        lambda *a, **k: build_called.__setitem__("yes", True),
    )
    source_id = _seed_source(client)

    started = client.post("/api/tutorial/start", json={"source_id": source_id})
    state = _poll(client, started.json()["token"])

    assert state["passed"] is False
    assert state["product_id"] is None
    assert build_called["yes"] is False
    assert client.get("/api/tutorial/products").json() == []


def test_a_late_success_after_retries_still_dispenses(tmp_path, monkeypatch):
    # First two proposals are unusable, the third is good — proves the bounded retry gives the
    # proposer another chance while the gate still decides each one on its own merits.
    provider = SequencedProvider({"tutorial-generator": ["nope", "still nope", GOOD_CONTENT]})
    client = _client(tmp_path, provider, monkeypatch)
    source_id = _seed_source(client)

    started = client.post("/api/tutorial/start", json={"source_id": source_id})
    state = _poll(client, started.json()["token"])

    assert state["passed"] is True
    assert state["product_id"]


def test_dispense_runs_a_copy_of_the_products_own_container(tmp_path, monkeypatch):
    client = _client(tmp_path, ScriptedProvider({"tutorial-generator": GOOD_CONTENT}), monkeypatch)
    source_id = _seed_source(client)
    started = client.post("/api/tutorial/start", json={"source_id": source_id})
    state = _poll(client, started.json()["token"])
    product_id = state["product_id"]

    seen_image = {}

    def _fake_dispense(image):
        seen_image["image"] = image
        return DispensedCopy(container_id="c_abc123", image=image, url="http://127.0.0.1:55001", port=55001)

    monkeypatch.setattr("hub.app.dispense_copy", _fake_dispense)
    resp = client.post(f"/api/tutorial/products/{product_id}/dispense")
    assert resp.status_code == 200
    assert resp.json() == {"container_id": "c_abc123", "url": "http://127.0.0.1:55001"}
    assert seen_image["image"] == state["container_image"]

    returned = {"id": None}
    monkeypatch.setattr("hub.app.return_copy", lambda cid: returned.__setitem__("id", cid))
    ret = client.post("/api/tutorial/copies/c_abc123/return")
    assert ret.status_code == 200
    assert returned["id"] == "c_abc123"


def test_dispense_unknown_product_is_a_404(tmp_path, monkeypatch):
    client = _client(tmp_path, ScriptedProvider({}), monkeypatch)
    resp = client.post("/api/tutorial/products/mem_nope/dispense")
    assert resp.status_code == 404


def test_dispense_without_a_built_container_is_a_409(tmp_path, monkeypatch):
    client = _client(
        tmp_path, ScriptedProvider({"tutorial-generator": GOOD_CONTENT}), monkeypatch, build_ok=False,
    )
    source_id = _seed_source(client)
    started = client.post("/api/tutorial/start", json={"source_id": source_id})
    state = _poll(client, started.json()["token"])

    resp = client.post(f"/api/tutorial/products/{state['product_id']}/dispense")
    assert resp.status_code == 409
