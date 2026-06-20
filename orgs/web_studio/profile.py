"""P22 — the aesthetic profile: the system learns YOUR taste from what you approve.

Taste has no oracle except your past approvals — so we accumulate them. Each human-approved
build feeds its aesthetic criteria into a profile (your standing preferences). The profile then
flows back two ways: it FILLS the gaps in a new spec (so you only specify what differs from your
usual taste — the interview shortens), and it provides standing checks. Not weights, not "smarter
at design" — smarter at *you*, and provably so: every input was a build you actually signed off on.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from orgs.web_studio.aesthetics import AestheticCriteria, normalize_color
from orgs.web_studio.interview import CreateSpec


@dataclass
class AestheticProfile:
    approvals: int = 0
    theme_votes: dict[str, int] = field(default_factory=dict)  # "dark"->n, "light"->m
    palette: list[str] = field(default_factory=list)           # accumulated approved colors
    fonts: list[str] = field(default_factory=list)             # accumulated approved fonts
    min_contrast: float | None = None                          # strictest contrast you've wanted

    def update(self, a: AestheticCriteria) -> None:
        """Fold one human-approved build's aesthetic into the standing profile."""
        self.approvals += 1
        if a.theme:
            self.theme_votes[a.theme] = self.theme_votes.get(a.theme, 0) + 1
        if a.palette:
            self.palette = sorted(set(self.palette) | {normalize_color(c) for c in a.palette})
        if a.fonts:
            self.fonts = sorted(set(self.fonts) | {f.strip().lower() for f in a.fonts})
        if a.min_contrast is not None:
            self.min_contrast = a.min_contrast if self.min_contrast is None \
                else max(self.min_contrast, a.min_contrast)

    def theme(self) -> str | None:
        return max(self.theme_votes, key=lambda k: self.theme_votes[k]) if self.theme_votes else None

    def as_criteria(self) -> AestheticCriteria:
        return AestheticCriteria(
            theme=self.theme(),
            min_contrast=self.min_contrast,
            fonts=self.fonts or None,
            palette=self.palette or None,
        )


def profile_hint(profile: AestheticProfile) -> str | None:
    """A human-readable summary of the learned profile, to feed the interview as 'known
    preferences' so it doesn't re-ask them (the interview shortens over time)."""
    if profile.approvals == 0:
        return None
    parts = []
    if profile.theme():
        parts.append(f"theme={profile.theme()}")
    if profile.palette:
        parts.append(f"palette={', '.join(profile.palette)}")
    if profile.fonts:
        parts.append(f"fonts={', '.join(profile.fonts)}")
    if profile.min_contrast is not None:
        parts.append(f"min_contrast={profile.min_contrast}")
    return "; ".join(parts) if parts else None


def apply_profile(profile: AestheticProfile, spec: CreateSpec) -> CreateSpec:
    """Fill a spec's UNSET aesthetic fields from the learned profile — you only specify what
    differs from your standing taste; the profile supplies the rest."""
    p = profile.as_criteria()
    a = spec.aesthetics
    filled = AestheticCriteria(
        theme=a.theme if a.theme is not None else p.theme,
        min_contrast=a.min_contrast if a.min_contrast is not None else p.min_contrast,
        fonts=a.fonts if a.fonts else p.fonts,
        palette=a.palette if a.palette else p.palette,
    )
    return CreateSpec(
        title=spec.title, description=spec.description,
        required_elements=spec.required_elements, aesthetics=filled,
    )


class ProfileStore:
    """File-per-profile, mirroring the memory/run stores; a DB can slot behind it when hosted."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> AestheticProfile:
        if not self.path.exists():
            return AestheticProfile()
        d: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return AestheticProfile(
            approvals=int(d.get("approvals", 0)),
            theme_votes=dict(d.get("theme_votes", {})),
            palette=list(d.get("palette", [])),
            fonts=list(d.get("fonts", [])),
            min_contrast=d.get("min_contrast"),
        )

    def save(self, profile: AestheticProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(profile), indent=2), encoding="utf-8")
