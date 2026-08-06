"""Caption parsing for the transcript fetcher (P28b) — offline, deterministic.

The network fetch itself is a thin shell over yt-dlp + urllib (exercised live, not in CI); what
matters to test here is that the two caption formats reduce to clean spoken text, and that the
ScriptedFetcher honours its 'no transcript -> raise' contract so the fail-honestly path is testable.
ArticleFetcher's actual HTTP call is exercised live, not here, but its post-fetch sanity check
(reject page JS/JSON masquerading as article text — see `_looks_like_page_script`) is pure logic
and gets real coverage below via a mocked httpx/trafilatura.
ChainedFetcher's orchestration (try each fetcher, fall through on failure) IS pure and offline, so
that gets real coverage below.
"""

from __future__ import annotations

import pytest

from commons.ingest import (
    ArticleFetcher,
    ChainedFetcher,
    FetchedTranscript,
    ScriptedFetcher,
    TranscriptUnavailable,
    _looks_like_page_script,
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


# Reproduces a live incident (2026-07-31): sharing a YouTube URL whose captions yt-dlp couldn't
# read fell through to ArticleFetcher, which fetched the raw watch page. trafilatura's
# boilerplate-removal found no article content on it and fell back to the largest text block on
# the page — the `window.WIZ_global_data = {...}` state blob Google inlines into every page —
# and that ~2MB of JavaScript got persisted into the commons as if it were a transcript.
def test_looks_like_page_script_detects_wiz_global_data_blob():
    blob = 'window.WIZ_global_data = {"key": "value", "nested": {"a": 1}};'
    assert _looks_like_page_script(blob) is True


@pytest.mark.parametrize(
    "blob",
    [
        'window.WIZ_global_data = {"a": 1};',
        'ytInitialData = {"a": 1};',
        'var x = {"a": 1};',
        'let x = {"a": 1};',
        'const x = {"a": 1};',
        '{"a": 1, "b": [1, 2, 3]}',  # bare JSON object, no assignment prefix
        '[1, 2, 3]',  # bare JSON array
    ],
)
def test_looks_like_page_script_detects_various_js_and_json_shapes(blob):
    assert _looks_like_page_script(blob) is True


@pytest.mark.parametrize(
    "prose",
    [
        "How To Install A Garbage Disposal. First, shut off the power at the breaker.",
        "The quick brown fox jumps over the lazy dog. It happened again yesterday.",
        "",
    ],
)
def test_looks_like_page_script_accepts_ordinary_prose(prose):
    assert _looks_like_page_script(prose) is False


def test_article_fetcher_raises_instead_of_persisting_a_script_blob(monkeypatch):
    import httpx
    import trafilatura

    class _FakeResponse:
        text = "<html>irrelevant to this test, trafilatura.extract is mocked below</html>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse())
    monkeypatch.setattr(
        trafilatura,
        "extract",
        lambda *a, **k: 'window.WIZ_global_data = {"huge": "blob of page state"};',
    )

    with pytest.raises(TranscriptUnavailable, match="page script/data"):
        ArticleFetcher().fetch("https://youtube.com/watch?v=Q2oJxlwJf9g")


def test_article_fetcher_raises_on_anomalously_large_extraction(monkeypatch):
    import httpx
    import trafilatura

    class _FakeResponse:
        text = "<html></html>"

        def raise_for_status(self) -> None:
            return None

    # Ordinary prose, but far larger than any real article/transcript extraction should be.
    huge_prose = "This is a normal sentence. " * 20_000

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse())
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: huge_prose)

    with pytest.raises(TranscriptUnavailable, match="page script/data"):
        ArticleFetcher().fetch("https://example.com/suspiciously-huge-page")


def test_article_fetcher_accepts_normal_article_text(monkeypatch):
    import httpx
    import trafilatura

    class _FakeMetadata:
        title = "A Normal Article"
        sitename = "Example News"

    class _FakeResponse:
        text = "<html></html>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse())
    monkeypatch.setattr(
        trafilatura, "extract", lambda *a, **k: "This is an ordinary article paragraph."
    )
    monkeypatch.setattr(trafilatura, "extract_metadata", lambda *a, **k: _FakeMetadata())

    result = ArticleFetcher().fetch("https://example.com/normal-article")
    assert result.text == "This is an ordinary article paragraph."
    assert result.title == "A Normal Article"
    assert result.channel == "Example News"
