"""hub/tutorial_container.py — needs a running Docker daemon, same skip contract as
test_container_executor.py. render_tutorial_page (pure) is tested unconditionally; build/dispense/
return are the real, slow, Docker-backed integration path.
"""

from __future__ import annotations

import urllib.request

import pytest

from hub.tutorial_container import (
    _detect_language,
    build_tutorial_image,
    dispense_copy,
    docker_available,
    image_tag,
    render_tutorial_page,
    return_copy,
)
from hub.tutorial_generate import TutorialContent, TutorialSection, TutorialStep


def test_image_tag_is_a_readable_docker_tag():
    assert image_tag("mem_abc123def456") == "veritas-tutorial-abc123def456:local"


# --- _detect_language: same heuristic the Hub UI's JS mirrors, kept honest by hand ------------

def test_detect_language_recognizes_json():
    assert _detect_language('{"a": 1, "b": [2, 3]}') == "json"


def test_detect_language_recognizes_bash():
    assert _detect_language("sudo apt-get install docker") == "bash"


def test_detect_language_recognizes_javascript():
    assert _detect_language("const x = () => console.log('hi')") == "javascript"


def test_detect_language_recognizes_markup():
    assert _detect_language("<!doctype html>\n<html><body></body></html>") == "markup"


def test_detect_language_falls_back_to_python():
    assert _detect_language("def add(a, b):\n    return a + b") == "python"
    assert _detect_language("") == "python"  # empty code never crashes the caller


def test_render_tutorial_page_escapes_content_and_includes_the_essentials():
    content = TutorialContent(
        overview="Summary with <script>alert(1)</script> in it.",
        materials=["2 cups flour"],
        sections=[TutorialSection(
            title="Mix", intro="", tip="",
            steps=[TutorialStep(instruction="Combine the ingredients.", code="print('hi')")],
        )],
    )
    page = render_tutorial_page("A Title", content, "https://example.com/vid", "Some Channel")
    assert "<script>alert(1)</script>" not in page  # escaped, not injected
    assert "&lt;script&gt;" in page
    assert "2 cups flour" in page
    assert "Combine the ingredients." in page
    assert "print(&#x27;hi&#x27;)" in page or "print('hi')" not in page  # escaped code, not raw
    assert "Some Channel" in page


def test_render_tutorial_page_highlights_code_with_a_detected_language():
    content = TutorialContent(
        overview="x", materials=["y"],
        sections=[TutorialSection(title="A", steps=[TutorialStep(instruction="do it", code="def f(): pass")])],
    )
    page = render_tutorial_page("Title", content, None, None)
    assert 'class="language-python"' in page
    assert "Prism.highlightAll();" in page  # the page actually invokes the highlighter
    assert "token" in page  # the vendored Prism source (defines .token classes) is inlined, not linked
    assert '<script src=' not in page  # inlined, never a network fetch from inside the container


def test_render_tutorial_page_omits_empty_optional_sections():
    content = TutorialContent(
        overview="just an overview", materials=["a thing"],
        sections=[TutorialSection(title="Do it", steps=[TutorialStep(instruction="Do the thing.")])],
    )
    page = render_tutorial_page("Title", content, None, None)
    assert "Quick Reference" not in page  # empty reference list
    assert "<pre>" not in page  # no step had code
    assert "class=\"tip\"" not in page  # no section had a tip


def test_render_tutorial_page_includes_materials_and_reference_when_present():
    content = TutorialContent(
        overview="x",
        materials=["115g dark chocolate", "3 large eggs"],
        sections=[TutorialSection(
            title="Bake", intro="Preheat first.", tip="Don't overbake.",
            steps=[TutorialStep(instruction="Bake for 25 minutes.")],
        )],
        reference=["Oven: 375°F for 25 min"],
    )
    page = render_tutorial_page("Souffle", content, None, None)
    assert "115g dark chocolate" in page
    assert "Preheat first." in page
    assert "Don&#x27;t overbake." in page or "Don't overbake." in page
    assert "Oven: 375" in page


pytestmark_docker = pytest.mark.skipif(not docker_available(), reason="needs a running Docker daemon")


@pytestmark_docker
def test_build_and_dispense_a_real_container_serves_the_page():
    content = TutorialContent(
        overview="A real end-to-end container test.",
        materials=["one test fixture"],
        sections=[TutorialSection(
            title="Verify", steps=[TutorialStep(instruction="Containers really are disposable.")],
        )],
    )
    tag = build_tutorial_image("mem_test_container", "Container Test Tutorial", content, None, None)
    try:
        copy = dispense_copy(tag)
        try:
            with urllib.request.urlopen(copy.url, timeout=10) as resp:
                body = resp.read().decode("utf-8")
            assert "Container Test Tutorial" in body
            assert "Containers really are disposable." in body
        finally:
            return_copy(copy.container_id)
    finally:
        import subprocess
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, timeout=30)
