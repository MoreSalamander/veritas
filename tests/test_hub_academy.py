"""The Academy shelf over the HTTP control plane: /api/academy/products lists packaged projects
from Veritas's own memory, and the generalized dispense endpoint serves BOTH shelves — a product
id found on the academy shelf dispenses exactly like a tutorial. Docker is monkeypatched out,
same discipline as test_hub_tutorial.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.memory import MemoryStore
from engine.model import ScriptedProvider
from hub.academy_container import AcademyProject, academy_record, image_tag
from hub.app import create_app
from hub.tutorial_container import DispensedCopy


def _seed_academy(tmp_path) -> str:
    project = AcademyProject(id="01-widgets", title="Widgets", tier="easy",
                             language="Python", pitch="Build a widget.", status="available")
    record = academy_record(project, "2 chapters verified", image_tag(project.id),
                            ["A window", "It moves"])
    MemoryStore(tmp_path / "memory" / "academy").persist(record)
    return record.id


def test_academy_products_lists_the_packaged_shelf(tmp_path):
    product_id = _seed_academy(tmp_path)
    client = TestClient(create_app(data_dir=tmp_path, provider=ScriptedProvider({})))

    products = client.get("/api/academy/products").json()
    assert len(products) == 1
    p = products[0]
    assert p["id"] == product_id
    assert p["kind"] == "academy"
    assert p["tier"] == "easy"
    assert p["chapters"] == ["A window", "It moves"]
    assert p["trust"] == "human-approved"
    assert p["container_image"] == "veritas-academy-01-widgets:local"


def test_dispense_finds_a_product_on_the_academy_shelf(tmp_path, monkeypatch):
    product_id = _seed_academy(tmp_path)
    client = TestClient(create_app(data_dir=tmp_path, provider=ScriptedProvider({})))

    seen = {}

    def _fake_dispense(image):
        seen["image"] = image
        return DispensedCopy(container_id="c_academy1", image=image,
                             url="http://127.0.0.1:55002", port=55002)

    monkeypatch.setattr("hub.app.dispense_copy", _fake_dispense)
    resp = client.post(f"/api/tutorial/products/{product_id}/dispense")
    assert resp.status_code == 200
    assert resp.json()["container_id"] == "c_academy1"
    assert seen["image"] == "veritas-academy-01-widgets:local"


def test_empty_academy_shelf_is_an_empty_list_not_an_error(tmp_path):
    client = TestClient(create_app(data_dir=tmp_path, provider=ScriptedProvider({})))
    assert client.get("/api/academy/products").json() == []
