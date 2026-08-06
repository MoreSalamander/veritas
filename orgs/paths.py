"""Repo-anchored paths and .env loading for processes that aren't the web app.

After the split, scripts and emitters can't rely on the hub having anchored
the data dir at import time — this is the one shared place that knows where
the mutable state lives. Anchored to the repo root, NOT the launch directory,
so every entry point finds the same runs no matter where it's started from
(relative "./hub_data" silently moved the data when launched from a
different cwd). VERITAS_DATA overrides.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    return _ROOT


def default_data_dir() -> Path:
    return Path(os.environ.get("VERITAS_DATA", str(_ROOT / "hub_data")))


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into the environment (without overriding anything
    already set). Without this the Claude models are in the catalog but unusable when a
    process is launched plainly — the SDK can't find ANTHROPIC_API_KEY. Stdlib only; no
    python-dotenv dependency."""
    env_path = path or (_ROOT / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))
