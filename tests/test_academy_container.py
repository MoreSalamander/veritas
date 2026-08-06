"""hub/academy_container.py — offline against a FAKE academy tree built in tmp_path, so no test
depends on the real sibling repo's content. Manifest/data.js parsing needs node (the module reads
reader data files the only honest way — by executing them), so those tests skip without it; the
one real docker build test skips without a daemon, same contract as test_tutorial_container.py.
"""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

import pytest

from products.academy.container import (
    AcademyPackagingError,
    AcademyProject,
    academy_record,
    assemble_context,
    build_academy_image,
    chapter_titles,
    image_tag,
    list_academy_projects,
    run_academy_gate,
)
from products.tutorial.container import dispense_copy, docker_available, return_copy

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate reader data files")


def _fake_academy(root: Path, gate_exit: int = 0) -> Path:
    reader = root / "reader"
    (reader / "projects" / "01-widgets").mkdir(parents=True)
    (reader / "manifest.js").write_text(
        'window.ACADEMY_PROJECTS = ['
        '{ id: "01-widgets", title: "Widgets", tier: "easy", language: "Python",'
        '  status: "available", pitch: "Build a widget." },'
        '{ id: "02-locked", title: "Locked", tier: "hard", language: "Python",'
        '  status: "coming", pitch: "Not yet." }];\n'
    )
    (reader / "index.html").write_text(
        '<html><head>\n'
        '  <link rel="preconnect" href="https://fonts.googleapis.com" />\n'
        '  <link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet" />\n'
        '  <link href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" rel="stylesheet" />\n'
        '</head><body>\n'
        '  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-core.min.js"></script>\n'
        '  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js"></script>\n'
        '  <script src="manifest.js"></script>\n'
        '  <script src="app.js"></script>\n'
        '</body></html>\n'
    )
    (reader / "app.js").write_text("// app\n")
    (reader / "styles.css").write_text("body { color: black; }\n")
    (reader / "projects" / "01-widgets" / "data.js").write_text(
        'window.ACADEMY_SOT = window.ACADEMY_SOT || {};\n'
        'window.ACADEMY_SOT["01-widgets"] = { project: "01-widgets", chapters: ['
        '{ id: 1, title: "A window" }, { id: 2, title: "It moves" }] };\n'
    )
    (reader / "projects" / "01-widgets" / "fulls.js").write_text("window.ACADEMY_FULLS = {};\n")
    tools = root / "tools"
    tools.mkdir()
    (tools / "check_lessons.py").write_text(
        "import sys\n"
        "print('2 chapters verified, prose matches code')\n"
        f"sys.exit({gate_exit})\n"
    )
    return root


def _project() -> AcademyProject:
    return AcademyProject(id="01-widgets", title="Widgets", tier="easy",
                          language="Python", pitch="Build a widget.", status="available")


@needs_node
def test_list_projects_returns_only_available(tmp_path):
    root = _fake_academy(tmp_path)
    projects = list_academy_projects(root)
    assert [p.id for p in projects] == ["01-widgets"]
    assert projects[0].pitch == "Build a widget."


@needs_node
def test_chapter_titles_come_from_the_data_sot(tmp_path):
    root = _fake_academy(tmp_path)
    assert chapter_titles("01-widgets", root) == ["A window", "It moves"]


def test_gate_pass_returns_the_checkers_own_evidence(tmp_path):
    root = _fake_academy(tmp_path, gate_exit=0)
    evidence = run_academy_gate("01-widgets", root)
    assert "prose matches code" in evidence


def test_gate_failure_refuses_with_the_checkers_output(tmp_path):
    root = _fake_academy(tmp_path, gate_exit=1)
    with pytest.raises(AcademyPackagingError, match="check_lessons FAILED"):
        run_academy_gate("01-widgets", root)


def test_assemble_context_scopes_and_self_contains_the_reader(tmp_path):
    root = _fake_academy(tmp_path)
    dest = tmp_path / "ctx"
    assemble_context(_project(), root, dest)

    index = (dest / "index.html").read_text()
    assert "googleapis.com" not in index and "cdnjs.cloudflare.com" not in index
    assert 'vendor/prism-tomorrow.min.css' in index
    assert 'location.hash = "#/01-widgets"' in index  # opens straight into the project

    manifest = (dest / "manifest.js").read_text()
    assert "01-widgets" in manifest and "02-locked" not in manifest

    assert (dest / "projects" / "01-widgets" / "data.js").exists()
    assert (dest / "projects" / "01-widgets" / "fulls.js").exists()
    assert (dest / "vendor" / "prism-core.min.js").exists()  # really vendored, not linked
    assert (dest / "Dockerfile").exists()


def test_assemble_context_refuses_a_missing_reader_file(tmp_path):
    root = _fake_academy(tmp_path)
    (root / "reader" / "projects" / "01-widgets" / "fulls.js").unlink()
    with pytest.raises(AcademyPackagingError, match="missing reader file"):
        assemble_context(_project(), root, tmp_path / "ctx")


def test_academy_record_is_deterministic_and_honestly_tiered(tmp_path):
    rec = academy_record(_project(), "gate evidence here", image_tag("01-widgets"),
                         ["A window", "It moves"])
    assert rec.id == "mem_academy_01_widgets"  # same project -> same id -> re-pack replaces
    assert rec.provenance["trust"] == "human-approved"
    assert rec.provenance["container_image"] == "veritas-academy-01-widgets:local"
    assert "academy" in rec.tags
    assert rec.provenance["accepted_because"] == "gate evidence here"


@pytest.mark.skipif(not docker_available(), reason="needs a running Docker daemon")
def test_build_and_dispense_a_real_academy_container(tmp_path):
    root = _fake_academy(tmp_path)
    tag = build_academy_image(_project(), root)
    try:
        copy = dispense_copy(tag)
        try:
            with urllib.request.urlopen(copy.url, timeout=10) as resp:
                body = resp.read().decode("utf-8")
            assert 'location.hash = "#/01-widgets"' in body
            with urllib.request.urlopen(copy.url + "/manifest.js", timeout=10) as resp:
                assert "01-widgets" in resp.read().decode("utf-8")
        finally:
            return_copy(copy.container_id)
    finally:
        import subprocess
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, timeout=30)
