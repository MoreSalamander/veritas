"""Caption parsing for the transcript fetcher (P28b) — offline, deterministic.

The network fetch itself is a thin shell over yt-dlp + urllib (exercised live, not in CI); what
matters to test here is that the two caption formats reduce to clean spoken text, and that the
ScriptedFetcher honours its 'no transcript -> raise' contract so the fail-honestly path is testable.
"""

from __future__ import annotations

import pytest

from hub.ingest import (
    FetchedTranscript,
    ScriptedFetcher,
    TranscriptUnavailable,
    _parse_json3,
    _strip_vtt,
)


def test_parse_json3_joins_segments():
    raw = (
        b'{"events":[{"segs":[{"utf8":"hello "},{"utf8":"world"}]},'
        b'{"segs":[{"utf8":"\\nsecond line"}]}]}'
    )
    assert _parse_json3(raw) == "hello world\nsecond line"


def test_strip_vtt_drops_timestamps_tags_and_dupes():
    vtt = (
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: en\n"
        "\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "the <00:00:01.500>quick brown fox\n"
        "\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "the quick brown fox\n"  # auto-captions repeat the rolling line
        "jumps over\n"
    )
    assert _strip_vtt(vtt) == "the quick brown fox\njumps over"


def test_scripted_fetcher_returns_known_and_raises_unknown():
    f = ScriptedFetcher({"u1": FetchedTranscript(text="hi", title="T")})
    assert f.fetch("u1").text == "hi"
    with pytest.raises(TranscriptUnavailable):
        f.fetch("missing")
