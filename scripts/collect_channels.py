#!/usr/bin/env python
"""Run the Knowledge Graph's channel-level auto-collector (hub/channel_collect.py).

Walks every channel in config/vouched_channels.json, fetches any video not
already in the commons, and persists it as a human-vouched source record —
the exact same containment a manually-pasted URL goes through at
POST /api/commons, just triggered per-channel instead of per-video.

A channel only appears in config/vouched_channels.json because a human put
it there — that file IS the vouching act. This script does no vouching of
its own; it only executes authorization a human already gave.

Usage:  .venv/bin/python scripts/collect_channels.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.memory import default_memory_store  # noqa: E402
from commons.channels import YtDlpChannelLister, collect_all, load_vouched_channels  # noqa: E402
from commons.ingest import YtDlpFetcher  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what each vouched channel currently publishes, without fetching or persisting",
    )
    args = parser.parse_args()

    config_path = ROOT / "config" / "vouched_channels.json"
    channels = load_vouched_channels(config_path)
    if not channels:
        print(f"no vouched channels in {config_path} — add one to collect from it")
        return

    if args.dry_run:
        lister = YtDlpChannelLister()
        for channel in channels:
            videos = lister.list_videos(channel.channel_url)
            print(f"{channel.title} ({channel.name}): {len(videos)} video(s) currently published")
        return

    commons = default_memory_store(ROOT / "hub_data" / "memory" / "commons")
    results = collect_all(config_path, YtDlpChannelLister(), YtDlpFetcher(), commons)

    total = sum(len(paths) for paths in results.values())
    for name, paths in results.items():
        print(f"{name}: collected {len(paths)} new video(s)")
    print(f"\n{total} new source record(s) added to the commons at {commons.base}")


if __name__ == "__main__":
    main()
