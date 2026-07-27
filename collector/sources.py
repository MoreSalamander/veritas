"""The source registry — read-only external data providers, config-driven.

Deliberately separate from `orgs/registry.py`'s `REGISTRY`: an `OrgType` is a
build-capable thing Veritas can run a goal through (`build: BuildFn`, a
roster, its own gates). A collector source has none of that — it's a
DataHub-shaped store Veritas only ever reads from. Forcing sources into
`OrgType` would mean a pile of unused fields on every entry; a sibling
catalog keeps "things Veritas can DO" and "things Veritas READS" honest.

Onboarding a new source — a new Hunter-style engine, or a future
Opportunity-shaped manager like Education/Career Agency AI — is one entry in
config/collector_sources.json. If the new manager is Opportunity-shaped it
reuses kind="opportunity_hub" outright; nothing here changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TrustDefault = Literal["auto", "held"]


@dataclass(frozen=True)
class SourceConfig:
    name: str
    title: str
    repo: str  # e.g. "~/MoreSalamander/crypto-hunter" — expanded via db_path_for
    kind: str  # looked up in readers.KIND_READERS
    color: str
    # A brand-new source starts held for a human; sources graduate to "auto"
    # via a config change once their track record earns it — never a code
    # change.
    default_trust: TrustDefault = "held"


def load_sources(path: Path) -> dict[str, SourceConfig]:
    with open(path) as f:
        raw: dict[str, dict[str, str]] = json.load(f)
    return {
        name: SourceConfig(
            name=name,
            title=cfg["title"],
            repo=cfg["repo"],
            kind=cfg["kind"],
            color=cfg["color"],
            default_trust=cfg.get("default_trust", "held"),  # type: ignore[arg-type]
        )
        for name, cfg in raw.items()
    }


def db_path_for(cfg: SourceConfig) -> Path:
    return Path(cfg.repo).expanduser() / "data" / "datahub.sqlite3"
