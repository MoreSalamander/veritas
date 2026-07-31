"""Channel-level auto-collection for the Second Brain — extends P28b.

`hub/ingest.py`'s `/api/commons` flow requires a human to vouch for one URL
at a time. This module lets a human vouch for a whole CHANNEL once instead
(`config/vouched_channels.json`), after which new videos published on that
channel are collected automatically.

The containment this whole system exists to protect does NOT move: every
record produced here still goes through the exact same
`MemoryRecord.from_source()` -> `MemoryStore.persist()` path a manually
pasted URL uses (`engine/memory.py`'s hard refusal of any source record
missing the `human-vouched` tag + a real URL, P28a), still attribution-only
downstream (`orgs/research_studio`'s `VouchedAttributionGate`). What changes
is WHERE the human's authorization happens — once per channel, in this
config file, instead of once per video via the API — not WHETHER it
happens. `captured_why` on every auto-collected record cites exactly which
channel-level authorization let it in, so the audit trail still traces to a
real human decision even though no human reviewed that specific video.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.memory import MemoryRecord, MemoryStore
from hub.ingest import TranscriptFetcher, TranscriptUnavailable


@dataclass(frozen=True)
class VouchedChannel:
    """One human-authorized channel. `vouched_by`/`vouched_at`/`why` are the
    audit trail for the channel-level authorization act itself."""

    name: str
    title: str
    channel_url: str
    vouched_by: str
    vouched_at: str
    why: str


def load_vouched_channels(path: Path) -> list[VouchedChannel]:
    """Load the human-maintained channel allowlist. A channel only appears
    here because a human added it — this file IS the vouching act, the same
    way clicking submit on a pasted URL is today."""
    with open(path) as f:
        raw: dict[str, dict[str, str]] = json.load(f)
    return [
        VouchedChannel(
            name=name,
            title=cfg["title"],
            channel_url=cfg["channel_url"],
            vouched_by=cfg["vouched_by"],
            vouched_at=cfg["vouched_at"],
            why=cfg["why"],
        )
        for name, cfg in raw.items()
    ]


@dataclass
class ChannelVideo:
    url: str
    title: str = ""


class ChannelLister(ABC):
    @abstractmethod
    def list_videos(self, channel_url: str) -> list[ChannelVideo]:
        """Return every video URL currently published on this channel."""


class ScriptedChannelLister(ChannelLister):
    """Offline lister for tests: returns a canned video list by channel URL,
    the same pattern as hub/ingest.py's ScriptedFetcher."""

    def __init__(self, by_channel: dict[str, list[ChannelVideo]] | None = None) -> None:
        self._by_channel = by_channel or {}

    def list_videos(self, channel_url: str) -> list[ChannelVideo]:
        return list(self._by_channel.get(channel_url, []))


class YtDlpChannelLister(ChannelLister):
    """Lists a channel's videos via yt-dlp's flat extraction (metadata only,
    no per-video network calls) — cheap enough to poll a channel regularly."""

    def list_videos(self, channel_url: str) -> list[ChannelVideo]:
        try:
            import yt_dlp
        except ImportError as e:  # pragma: no cover - environment-dependent
            raise TranscriptUnavailable("yt-dlp is not installed") from e

        opts = {"extract_flat": True, "quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
        return self._flatten(info.get("entries") or [])

    def _flatten(self, entries: list[dict[str, Any]]) -> list[ChannelVideo]:
        # extract_flat often nests a channel's tabs (Videos/Shorts/Live) as
        # sub-playlists rather than videos directly; flatten one level.
        videos: list[ChannelVideo] = []
        for entry in entries:
            if entry.get("_type") == "playlist":
                videos.extend(
                    ChannelVideo(url=sub["url"], title=sub.get("title", ""))
                    for sub in (entry.get("entries") or [])
                    if sub.get("url")
                )
            elif entry.get("url"):
                videos.append(ChannelVideo(url=entry["url"], title=entry.get("title", "")))
        return videos


def _already_collected_urls(commons: MemoryStore) -> set[str]:
    return {
        url
        for rec in commons.load_all()
        if rec.category == "source" and (url := rec.provenance.get("url"))
    }


def collect_channel(
    channel: VouchedChannel,
    lister: ChannelLister,
    fetcher: TranscriptFetcher,
    commons: MemoryStore,
) -> list[Path]:
    """Fetch and persist every not-yet-collected video from one vouched
    channel. Returns the paths of newly-persisted records. Skips videos
    whose transcript isn't available rather than failing the whole batch —
    same 'fail honestly, don't crash' contract as the manual /api/commons
    path (hub/ingest.py)."""
    seen = _already_collected_urls(commons)
    written: list[Path] = []
    for video in lister.list_videos(channel.channel_url):
        if video.url in seen:
            continue
        try:
            fetched = fetcher.fetch(video.url)
        except TranscriptUnavailable:
            continue
        record = MemoryRecord.from_source(
            url=video.url,
            transcript=fetched.text,
            channel=fetched.channel or channel.title,
            title=fetched.title or video.title or None,
            captured_why=(
                f"auto-collected from human-vouched channel '{channel.title}' "
                f"(vouched by {channel.vouched_by} on {channel.vouched_at}): {channel.why}"
            ),
        )
        written.append(commons.persist(record))
    return written


def collect_all(
    channels_config: Path,
    lister: ChannelLister,
    fetcher: TranscriptFetcher,
    commons: MemoryStore,
) -> dict[str, list[Path]]:
    """Run collect_channel() over every channel in the allowlist. Returns
    {channel_name: [newly-persisted paths]}."""
    return {
        channel.name: collect_channel(channel, lister, fetcher, commons)
        for channel in load_vouched_channels(channels_config)
    }
