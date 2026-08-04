"""Packages taichi-academy projects as vending-machine containers — one image per project,
each rung of the academy's skills ladder becoming a dispensable product.

The trust story here is DIFFERENT from the tutorial pipeline, and honestly so: nothing in this
module is LLM-generated. The academy's lessons were authored by a person and verified upstream by
the academy's own deterministic pipeline (reference implementations written and tested first,
lesson fragments compile-checked, prose SOT asserted against code SOT). So the admission gate
into the vending machine is not a new judgment — it is the academy's OWN checker,
`tools/check_lessons.py`, run at packaging time. Same verification model the project already
lives by, reused as the gate (doctrine rule 1: an org is defined by its verification model).
A project whose prose has drifted from its code does not get packaged. Trust tier:
human-approved — a person signed off this content, and a machine re-verified the signature.

The image is the academy's own static reader, scoped to the one project: same index/app/styles,
manifest filtered to a single card, the project's data.js + fulls.js, and the reader's CDN
dependencies (Prism, fonts) vendored/dropped so the container works fully offline — same
constraint as tutorial containers (hub/tutorial_container.py), same nginx base, same
build-once/dispense-many lifecycle.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from engine.memory import MemoryRecord
from hub.tutorial_container import _DOCKER

ACADEMY_ROOT = Path.home() / "MoreSalamander" / "taichi-academy"

# The vendored Prism files the rewritten reader points at — copied into every image from
# Veritas's own static vendor dir (the reader uses the exact same Prism 1.29.0 from cdnjs).
_VENDOR_DIR = Path(__file__).resolve().parent / "static" / "vendor" / "prism"
_VENDOR_FILES = ("prism-tomorrow.min.css", "prism-core.min.js", "prism-python.min.js")


class AcademyPackagingError(Exception):
    """Raised when a project can't be packaged — missing files, a failed gate, a failed build.
    The message carries the evidence; the caller surfaces it honestly rather than shipping anyway."""


@dataclass(frozen=True)
class AcademyProject:
    id: str
    title: str
    tier: str
    language: str
    pitch: str
    status: str


def _node_eval(js_path: Path, expression: str) -> object:
    """Evaluate a reader .js data file exactly the way the academy's own check_lessons.py does:
    let node execute it against a bare `window`, then print the requested expression as JSON.
    Not a regex parse — the file is code, so the only honest reader of it is a JS engine."""
    out = subprocess.run(
        ["node", "-e",
         f"global.window = {{}}; require({json.dumps(str(js_path))}); "
         f"console.log(JSON.stringify({expression}))"],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise AcademyPackagingError(f"{js_path.name} failed to evaluate: {out.stderr[-500:]}")
    return json.loads(out.stdout)


def list_academy_projects(academy_root: Path = ACADEMY_ROOT) -> list[AcademyProject]:
    """Every project in the reader's manifest with status 'available' — the packagable set."""
    manifest = academy_root / "reader" / "manifest.js"
    if not manifest.exists():
        raise AcademyPackagingError(f"no manifest at {manifest}")
    raw = _node_eval(manifest, "window.ACADEMY_PROJECTS")
    if not isinstance(raw, list):
        raise AcademyPackagingError("manifest did not evaluate to a project list")
    projects = [
        AcademyProject(
            id=str(p.get("id", "")), title=str(p.get("title", "")), tier=str(p.get("tier", "")),
            language=str(p.get("language", "")), pitch=str(p.get("pitch", "")),
            status=str(p.get("status", "")),
        )
        for p in raw
        if isinstance(p, dict)
    ]
    return [p for p in projects if p.status == "available" and p.id]


def chapter_titles(project_id: str, academy_root: Path = ACADEMY_ROOT) -> list[str]:
    data_js = academy_root / "reader" / "projects" / project_id / "data.js"
    sot = _node_eval(data_js, f"window.ACADEMY_SOT[{json.dumps(project_id)}]")
    if not isinstance(sot, dict):
        raise AcademyPackagingError(f"no SOT for {project_id} in its data.js")
    return [str(ch.get("title", "")) for ch in sot.get("chapters", []) if isinstance(ch, dict)]


def run_academy_gate(project_id: str, academy_root: Path = ACADEMY_ROOT) -> str:
    """The HARD gate: the academy's own anti-drift checker. Passes -> returns its evidence text.
    Fails -> AcademyPackagingError with the checker's own output, so the refusal is explainable.
    Prefers the academy's venv python when present; the checker itself is stdlib-only, so the
    fallback to this interpreter is safe."""
    checker = academy_root / "tools" / "check_lessons.py"
    if not checker.exists():
        raise AcademyPackagingError(f"no checker at {checker}")
    academy_python = academy_root / ".venv" / "bin" / "python"
    python = str(academy_python) if academy_python.exists() else sys.executable
    out = subprocess.run(
        [python, str(checker), "--project", project_id],
        cwd=academy_root, capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise AcademyPackagingError(
            f"check_lessons FAILED for {project_id}: {(out.stdout + out.stderr)[-800:]}"
        )
    evidence = (out.stdout or "").strip() or "check_lessons passed: prose SOT matches code SOT"
    return evidence[-500:]


def image_tag(project_id: str) -> str:
    return f"veritas-academy-{project_id}:local"


def _rewrite_index(index_html: str, project_id: str) -> str:
    """Make the reader self-contained and single-project: CDN Prism -> vendored copies, Google
    Fonts dropped (every family in styles.css carries a fallback stack), and a one-liner that
    opens the project directly so the single-card landing never needs a click."""
    out = index_html
    out = re.sub(r'\s*<link[^>]*fonts\.g(?:oogleapis|static)\.com[^>]*/?>', "", out)
    out = out.replace(
        "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css",
        "vendor/prism-tomorrow.min.css",
    )
    out = out.replace(
        "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-core.min.js",
        "vendor/prism-core.min.js",
    )
    out = out.replace(
        "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js",
        "vendor/prism-python.min.js",
    )
    autoload = f'<script>if (!location.hash) location.hash = "#/{project_id}";</script>'
    out = out.replace('<script src="app.js">', autoload + '\n  <script src="app.js">')
    return out


def assemble_context(project: AcademyProject, academy_root: Path, dest: Path) -> None:
    """Build the docker context for one project's image: the reader, scoped to that project.
    Separate from the docker invocation so tests can verify the exact files that would ship
    without needing a daemon."""
    reader = academy_root / "reader"
    project_dir = reader / "projects" / project.id
    for required in (reader / "index.html", reader / "app.js", reader / "styles.css",
                     project_dir / "data.js", project_dir / "fulls.js"):
        if not required.exists():
            raise AcademyPackagingError(f"missing reader file: {required}")

    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(reader / "app.js", dest / "app.js")
    shutil.copy(reader / "styles.css", dest / "styles.css")
    (dest / "index.html").write_text(
        _rewrite_index((reader / "index.html").read_text(encoding="utf-8"), project.id),
        encoding="utf-8",
    )
    # The manifest, filtered to this one card — the landing page IS the product, nothing else's.
    entry = {"id": project.id, "title": project.title, "tier": project.tier,
             "language": project.language, "status": "available", "pitch": project.pitch}
    (dest / "manifest.js").write_text(
        "window.ACADEMY_PROJECTS = " + json.dumps([entry]) + ";\n", encoding="utf-8",
    )
    proj_dest = dest / "projects" / project.id
    proj_dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(project_dir / "data.js", proj_dest / "data.js")
    shutil.copy(project_dir / "fulls.js", proj_dest / "fulls.js")

    vendor_dest = dest / "vendor"
    vendor_dest.mkdir(exist_ok=True)
    for name in _VENDOR_FILES:
        src = _VENDOR_DIR / name
        if not src.exists():
            raise AcademyPackagingError(f"missing vendored file: {src}")
        shutil.copy(src, vendor_dest / name)

    (dest / "Dockerfile").write_text(
        "FROM nginx:alpine\nCOPY . /usr/share/nginx/html/\nRUN rm /usr/share/nginx/html/Dockerfile\n",
        encoding="utf-8",
    )


def build_academy_image(project: AcademyProject, academy_root: Path = ACADEMY_ROOT) -> str:
    """`docker build` one project's reader image. Idempotent: same project -> same tag,
    overwritten in place, exactly like tutorial images."""
    tag = image_tag(project.id)
    with tempfile.TemporaryDirectory() as tmp:
        context = Path(tmp)
        assemble_context(project, academy_root, context)
        proc = subprocess.run(
            [_DOCKER, "build", "-t", tag, str(context)],
            capture_output=True, text=True, timeout=300,
        )
    if proc.returncode != 0:
        raise AcademyPackagingError(f"docker build failed for {tag}: {proc.stderr[-1000:]}")
    return tag


def academy_record(project: AcademyProject, gate_evidence: str, tag: str,
                   chapters: list[str]) -> MemoryRecord:
    """Veritas's record of a packaged academy product. Deterministic id per project, so
    re-packaging replaces the record instead of accumulating duplicates — the academy version
    of tutorial upsert-by-source semantics."""
    return MemoryRecord(
        id=f"mem_academy_{project.id.replace('-', '_')}",
        category="artifact",
        title=f"Academy: {project.title}",
        body=json.dumps({
            "pitch": project.pitch, "tier": project.tier, "language": project.language,
            "chapters": chapters,
        }),
        tags=["academy", project.tier],
        provenance={
            "created_by": "taichi-academy",
            "rationale": f"skills-ladder checkpoint {project.id}, packaged as a dispensable reader",
            "accepted_because": gate_evidence,
            "trust": "human-approved",
            "verified_by": "tools/check_lessons.py — the academy's own anti-drift gate, "
                           "run at packaging time",
            "project_id": project.id,
            "container_image": tag,
        },
    )
