"""Channel-level auto-collection (hub/channel_collect.py) — offline, deterministic.

Proves the part that matters: a channel-level vouch still produces records
that satisfy engine/memory.py's human-vouched containment exactly like a
manually-pasted URL would, dedup skips already-collected videos, and an
unavailable transcript is skipped rather than failing the whole batch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.memory import MemoryStore, TRUST_VOUCHED
from commons.channels import (
    ChannelVideo,
    ScriptedChannelLister,
    VouchedChannel,
    collect_channel,
    load_vouched_channels,
)
from commons.ingest import FetchedTranscript, ScriptedFetcher


def _channel(**overrides) -> VouchedChannel:
    defaults = dict(
        name="test_channel",
        title="Test Channel",
        channel_url="https://example.com/@testchannel",
        vouched_by="tester",
        vouched_at="2026-07-30",
        why="unit test fixture",
    )
    defaults.update(overrides)
    return VouchedChannel(**defaults)


def test_collect_channel_persists_every_new_video_as_human_vouched(tmp_path: Path):
    commons = MemoryStore(tmp_path / "commons")
    channel = _channel()
    lister = ScriptedChannelLister(
        {channel.channel_url: [ChannelVideo(url="https://vid/1", title="Video 1")]}
    )
    fetcher = ScriptedFetcher({"https://vid/1": FetchedTranscript(text="hello world")})

    written = collect_channel(channel, lister, fetcher, commons)

    assert len(written) == 1
    [record] = commons.load_all()
    assert record.category == "source"
    assert TRUST_VOUCHED in record.tags
    assert record.provenance["trust"] == TRUST_VOUCHED
    assert record.provenance["url"] == "https://vid/1"
    # The audit trail names the channel-level authorization, not the video.
    assert channel.title in record.provenance["captured_why"]
    assert channel.vouched_by in record.provenance["captured_why"]


def test_collect_channel_skips_already_collected_urls(tmp_path: Path):
    commons = MemoryStore(tmp_path / "commons")
    channel = _channel()
    lister = ScriptedChannelLister(
        {channel.channel_url: [ChannelVideo(url="https://vid/1", title="Video 1")]}
    )
    fetcher = ScriptedFetcher({"https://vid/1": FetchedTranscript(text="hello world")})

    first = collect_channel(channel, lister, fetcher, commons)
    second = collect_channel(channel, lister, fetcher, commons)  # same video again

    assert len(first) == 1
    assert second == []  # already in the commons, not re-persisted
    assert len(commons.load_all()) == 1


def test_collect_channel_skips_unavailable_transcripts_without_failing_batch(tmp_path: Path):
    commons = MemoryStore(tmp_path / "commons")
    channel = _channel()
    lister = ScriptedChannelLister(
        {
            channel.channel_url: [
                ChannelVideo(url="https://vid/no-captions", title="No captions"),
                ChannelVideo(url="https://vid/2", title="Has captions"),
            ]
        }
    )
    # Only vid/2 has a scripted transcript -> vid/no-captions raises TranscriptUnavailable.
    fetcher = ScriptedFetcher({"https://vid/2": FetchedTranscript(text="hello")})

    written = collect_channel(channel, lister, fetcher, commons)

    assert len(written) == 1
    [record] = commons.load_all()
    assert record.provenance["url"] == "https://vid/2"


def test_load_vouched_channels_reads_config(tmp_path: Path):
    config = tmp_path / "vouched_channels.json"
    config.write_text(
        """{
        "example": {
            "title": "Example Channel",
            "channel_url": "https://example.com/@example",
            "vouched_by": "tester",
            "vouched_at": "2026-07-30",
            "why": "unit test"
        }
    }"""
    )
    [channel] = load_vouched_channels(config)
    assert channel.name == "example"
    assert channel.title == "Example Channel"
    assert channel.channel_url == "https://example.com/@example"
