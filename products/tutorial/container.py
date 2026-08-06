"""Packages a dispensed tutorial as a real Docker image, and hands out disposable copies of it —
the literal container half of "each thing that's made becomes a container; copies of that
container are what we give out" (the Entropy container-distribution thesis, applied here first).

Two separate operations, on purpose: BUILD happens once per tutorial, when its gate passes — the
content gets baked into a static page inside a tiny image, tagged by the tutorial's own record id.
DISPENSE happens every time someone presses the vending-machine button — a fresh `docker run -d
--rm` of that same image, a new disposable container each time, never the same box handed out
twice. This is the trusted-image / disposable-run split ContainerExecutor already uses for
untrusted code, borrowed here for a different reason: the image is reused, the instance isn't.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from products.tutorial.generate import TutorialContent, TutorialSection, TutorialStep

# Every dispensed container is a standalone page with no guaranteed outbound network — the same
# vendored Prism.js (MIT) the Hub UI itself uses gets inlined directly into each generated HTML
# page rather than linked, so a code block still renders VS-Code-Dark+-highlighted with the
# container fully offline. Read once at import time; these files never change at runtime.
_PRISM_DIR = Path(__file__).resolve().parent / "static" / "vendor" / "prism"
_PRISM_JS_ORDER = (
    "prism-core.min.js", "prism-markup.min.js", "prism-clike.min.js",
    "prism-python.min.js", "prism-javascript.min.js", "prism-bash.min.js", "prism-json.min.js",
)


def _load_prism_js() -> str:
    return "\n".join((_PRISM_DIR / name).read_text(encoding="utf-8") for name in _PRISM_JS_ORDER)


def _load_prism_css() -> str:
    return (_PRISM_DIR / "prism-vsc-dark-plus.css").read_text(encoding="utf-8")


_PRISM_JS = _load_prism_js()
_PRISM_CSS = _load_prism_css()
_PRISM_LANGS = {"python", "javascript", "bash", "json", "markup"}


def _detect_language(code: str) -> str:
    """Same heuristic as the Hub UI's detectLanguage() in hub/static/index.html, ported to
    Python — kept in sync by hand since one lives in a .js <script>, the other in this module; a
    tutorial's own step code has no language tag today, so something has to guess. Falls through
    to Python since that's the dominant case (every real code-typing-practice tutorial so far)."""
    s = code.strip()
    if not s:
        return "python"
    if re.match(r"^<!doctype html", s, re.IGNORECASE) or re.match(r"^<html[\s>]", s, re.IGNORECASE):
        return "markup"
    if re.match(r"^[{\[]", s) and re.search(r"[}\]]$", s):
        try:
            json.loads(s)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass
    if re.match(r"^#!.*\b(bash|sh)\b", s) or re.search(r"^\s*(sudo|apt-get|curl|docker|export|cd)\s", s, re.MULTILINE):
        return "bash"
    if re.search(r"\b(function|const|let|=>|console\.log|import .* from)\b", s):
        return "javascript"
    return "python"

# A GUI launchd agent (this hub normally runs as one — see com.moresalamander.veritashub.plist)
# gets launchd's minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), which does NOT include Homebrew's
# /opt/homebrew/bin — where Docker Desktop's CLI actually lives on this machine. shutil.which()
# alone silently returns None there even though `docker` works fine in any interactive shell, so
# a few common install locations are checked directly before giving up. Measured live: dispensing
# failed with FileNotFoundError: 'docker' under the LaunchAgent despite working from a terminal.
_DOCKER_FALLBACKS = ("/opt/homebrew/bin/docker", "/usr/local/bin/docker",
                     "/Applications/Docker.app/Contents/Resources/bin/docker")


def _find_docker() -> str:
    found = shutil.which("docker")
    if found:
        return found
    for candidate in _DOCKER_FALLBACKS:
        if Path(candidate).exists():
            return candidate
    return "docker"  # nothing found anywhere — let the eventual subprocess call fail loudly


_DOCKER = _find_docker()


def docker_available() -> bool:
    """Docker is installed AND the daemon answers — same check ContainerExecutor.available() uses,
    duplicated rather than imported so this module never depends on the sandbox executor's own
    security posture (--network none etc.), which would be wrong for a page that serves content."""
    try:
        return subprocess.run([_DOCKER, "info"], capture_output=True, timeout=20).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def image_tag(product_id: str) -> str:
    # Docker tags reject the leading "mem_" underscore-prefix pattern nowhere in particular, but
    # a short, readable slug beats the raw id for anyone reading `docker images` output.
    return f"veritas-tutorial-{product_id.removeprefix('mem_')}:local"


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_tutorial_page(
    title: str, content: TutorialContent, source_url: str | None, source_channel: str | None,
) -> str:
    """A small, fully self-contained HTML page — no external fonts/scripts loaded at runtime
    (Prism.js is inlined, not linked), since this ships inside an isolated container with no
    guarantee of outbound network access. Renders the manual shape in the order a person actually
    needs it: what you need, then ordered sections of numbered steps (with per-step, syntax-
    highlighted code and per-section tips — VS Code Dark+, the same theme the Hub UI itself uses),
    then the closing reference."""
    materials = "".join(f"<li>{_esc(m)}</li>" for m in content.materials)
    materials_html = f'<h2>What You Need</h2><ul class="materials">{materials}</ul>' if materials else ""

    sections_html = "".join(_render_section(i + 1, sec) for i, sec in enumerate(content.sections))

    reference_html = ""
    if content.reference:
        items = "".join(f"<li>{_esc(r)}</li>" for r in content.reference)
        reference_html = f'<h2>Quick Reference</h2><ul class="reference">{items}</ul>'

    src = (
        f'<p class="src">Source: <a href="{_esc(source_url)}">{_esc(source_channel or source_url)}</a></p>'
        if source_url else ""
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_esc(title)}</title>
<style>
  body {{ background:#0a0e0c; color:#ece7d8; font-family:'IBM Plex Mono',ui-monospace,monospace;
          max-width:760px; margin:40px auto; padding:0 24px 60px; line-height:1.6; }}
  h1 {{ color:#e8c468; font-size:22px; margin-bottom:6px; }}
  h2 {{ color:#7f8c84; font-size:13px; letter-spacing:1px; text-transform:uppercase; margin-top:32px; }}
  h3 {{ color:#ece7d8; font-size:16px; margin: 26px 0 4px; }}
  .overview {{ font-size:14.5px; color:#c8c2af; }}
  a {{ color:#e8c468; }}
  .src {{ color:#7f8c84; font-size:12px; }}
  .badge {{ display:inline-block; border:1px solid #e8c468; color:#e8c468; font-size:10px;
            letter-spacing:.1em; text-transform:uppercase; padding:2px 8px; margin-bottom:14px; }}
  ul.materials li {{ margin-bottom: 4px; }}
  .section-intro {{ color:#a8a293; font-size:13.5px; margin: 4px 0 10px; }}
  ol.steps {{ margin: 0 0 4px; padding-left: 22px; }}
  ol.steps li {{ margin-bottom: 8px; }}
  .tip {{ background: rgba(232,196,104,.07); border-left: 3px solid #e8c468; padding: 8px 12px;
          font-size: 13px; color:#d9c98f; margin: 10px 0 4px; border-radius: 0 6px 6px 0; }}
  .tip b {{ color:#e8c468; }}
  ul.reference {{ font-size: 13px; color:#c8c2af; }}
  ul.reference li {{ margin-bottom: 3px; }}
</style>
<style>{_PRISM_CSS}</style>
</head>
<body>
  <div class="badge">Dispensed by Veritas — Entropy OS</div>
  <h1>{_esc(title)}</h1>
  {src}
  <p class="overview">{_esc(content.overview)}</p>
  {materials_html}
  {sections_html}
  {reference_html}
<script>{_PRISM_JS}</script>
<script>Prism.highlightAll();</script>
</body></html>
"""


def _render_section(number: int, section: TutorialSection) -> str:
    intro_html = f'<p class="section-intro">{_esc(section.intro)}</p>' if section.intro else ""
    steps_html = "".join(_render_step(s) for s in section.steps)
    tip_html = f'<div class="tip"><b>Tip —</b> {_esc(section.tip)}</div>' if section.tip else ""
    return (
        f"<h3>{number}. {_esc(section.title)}</h3>"
        f'{intro_html}<ol class="steps">{steps_html}</ol>{tip_html}'
    )


def _render_step(step: TutorialStep) -> str:
    if not step.code:
        return f"<li>{_esc(step.instruction)}</li>"
    lang = _detect_language(step.code)
    code_html = f'<pre class="language-{lang}"><code class="language-{lang}">{_esc(step.code)}</code></pre>'
    return f"<li>{_esc(step.instruction)}{code_html}</li>"


def build_tutorial_image(
    product_id: str, title: str, content: TutorialContent,
    source_url: str | None, source_channel: str | None,
) -> str:
    """`docker build` a tiny, self-contained image serving this tutorial as a static page.
    Idempotent by design: rebuilding the same product_id overwrites the same tag, so a re-run
    (regenerating the same source) replaces the stock instead of littering the image list."""
    tag = image_tag(product_id)
    page = render_tutorial_page(title, content, source_url, source_channel)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "index.html").write_text(page, encoding="utf-8")
        (tmp_path / "Dockerfile").write_text(
            "FROM nginx:alpine\nCOPY index.html /usr/share/nginx/html/index.html\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [_DOCKER, "build", "-t", tag, str(tmp_path)],
            capture_output=True, text=True, timeout=180,
        )
    if proc.returncode != 0:
        raise RuntimeError(f"docker build failed for {tag}: {proc.stderr[-1000:]}")
    return tag


@dataclass(frozen=True)
class DispensedCopy:
    container_id: str
    image: str
    url: str
    port: int


def dispense_copy(image: str) -> DispensedCopy:
    """`docker run` a fresh, disposable copy of an already-built tutorial image, bound to a
    Docker-assigned free port on loopback only. `--rm` means stopping it also removes it — a
    copy you're handed, not a shared instance everyone reaches through the same box."""
    proc = subprocess.run(
        [_DOCKER, "run", "--rm", "-d", "-p", "127.0.0.1::80", image],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker run failed for {image}: {proc.stderr[-1000:]}")
    container_id = proc.stdout.strip()
    port_proc = subprocess.run(
        [_DOCKER, "port", container_id, "80/tcp"], capture_output=True, text=True, timeout=10,
    )
    if port_proc.returncode != 0 or not port_proc.stdout.strip():
        subprocess.run([_DOCKER, "stop", "-t", "1", container_id], capture_output=True, timeout=10)
        raise RuntimeError(f"could not read the assigned port for {container_id}: {port_proc.stderr}")
    host_port = int(port_proc.stdout.strip().rsplit(":", 1)[-1])
    _wait_until_accepting(host_port)
    return DispensedCopy(
        container_id=container_id, image=image, url=f"http://127.0.0.1:{host_port}", port=host_port,
    )


def _wait_until_accepting(port: int, timeout: float = 5.0) -> None:
    """`docker run -d` returns the instant the process starts, not once nginx is actually serving
    — measured live, twice: a bare TCP connect (the first version of this check) still raced,
    because the kernel accepts a connection into the listen backlog before nginx's worker is
    actually ready to answer it, so the request landed anyway and got a reset. An HTTP-level GET
    is the honest readiness signal — if it 200s, the page really is servable. Best-effort: if the
    daemon never comes up, the caller's own request will surface that failure clearly on its own.
    """
    import urllib.error
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.05)


def return_copy(container_id: str) -> None:
    """Stop a dispensed copy. `--rm` on the original `run` means stopping also removes it —
    this is the whole lifecycle, there is no separate cleanup step."""
    subprocess.run([_DOCKER, "stop", "-t", "2", container_id], capture_output=True, timeout=15)
