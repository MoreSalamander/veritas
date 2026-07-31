"""Caption parsing for the transcript fetcher (P28b) — offline, deterministic.

The network fetch itself is a thin shell over yt-dlp + urllib (exercised live, not in CI); what
matters to test here is that the two caption formats reduce to clean spoken text, and that the
ScriptedFetcher honours its 'no transcript -> raise' contract so the fail-honestly path is testable.
ArticleFetcher is the same story as YtDlpFetcher — its network fetch is exercised live, not here.
ChainedFetcher's orchestration (try each fetcher, fall through on failure) IS pure and offline, so
that gets real coverage below.
"""

from __future__ import annotations

import pytest

from hub.ingest import (
    ChainedFetcher,
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


def test_chained_fetcher_falls_through_to_the_next_fetcher_on_failure():
    # Simulates the real case: YtDlpFetcher finds no video on this URL, so
    # ChainedFetcher falls through to an article-text fetcher instead.
    video_fetcher = ScriptedFetcher({"has-video": FetchedTranscript(text="captions")})
    article_fetcher = ScriptedFetcher({"webpage": FetchedTranscript(text="article body")})
    chained = ChainedFetcher([video_fetcher, article_fetcher])

    assert chained.fetch("has-video").text == "captions"  # first fetcher succeeds
    assert chained.fetch("webpage").text == "article body"  # falls through to the second


def test_chained_fetcher_raises_with_combined_reasons_when_all_fail():
    chained = ChainedFetcher([ScriptedFetcher({}), ScriptedFetcher({})])
    with pytest.raises(TranscriptUnavailable, match="no scripted transcript"):
        chained.fetch("nothing-has-this")


def test_chained_fetcher_requires_at_least_one_fetcher():
    with pytest.raises(ValueError, match="at least one fetcher"):
        ChainedFetcher([])
