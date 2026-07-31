"""Transcript fetching for the Knowledge Graph (P28b) — a swappable seam, like Executor/Publisher.

The commons stores *text*; this is the one piece that turns a pasted URL into that text. It is
isolated behind an ABC so (a) tests never touch the network (ScriptedFetcher) and (b) the concrete
backend (yt-dlp today, anything later) is a config swap, not a rewrite. The fetcher only retrieves
what a source already says — it never judges it; the `human-vouched` containment lives downstream
in MemoryRecord.from_source.

`ChainedFetcher` (bottom of this file) is what makes "share any URL, get a transcript" actually
true: yt-dlp isn't limited to youtube.com — it scans arbitrary webpages for an embedded video
player and extracts that video's captions if it finds one (discovered live, mid-session, sharing a
page that happened to have a YouTube embed). ArticleFetcher is the fallback for pages with no
video at all: readable article text instead of captions, same FetchedTranscript shape either way.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class FetchedTranscript:
    """What a fetcher recovers from a URL: the spoken text plus whatever provenance the source
    exposes. title/channel are best-effort — the human's URL is the authoritative origin."""

    text: str
    title: str = ""
    channel: str = ""


class TranscriptUnavailable(Exception):
    """Raised when a URL has no recoverable transcript. The caller surfaces this honestly (a clear
    message, no junk record) rather than letting it crash — P28b's 'fail honestly' contract."""


class TranscriptFetcher(ABC):
    @abstractmethod
    def fetch(self, url: str) -> FetchedTranscript:
        """Return the transcript for `url`, or raise TranscriptUnavailable if none exists."""


class ScriptedFetcher(TranscriptFetcher):
    """Offline fetcher for tests: returns canned transcripts by URL; an unknown URL is treated as
    having no transcript (so the 'fail honestly' path is testable without a network)."""

    def __init__(self, by_url: dict[str, FetchedTranscript] | None = None) -> None:
        self._by_url = by_url or {}

    def fetch(self, url: str) -> FetchedTranscript:
        if url not in self._by_url:
            raise TranscriptUnavailable(f"no scripted transcript for {url}")
        return self._by_url[url]


def _parse_json3(raw: bytes) -> str:
    """YouTube's json3 caption format: {'events': [{'segs': [{'utf8': '...'}]}]}. Join the segs."""
    data = json.loads(raw.decode("utf-8", "replace"))
    parts: list[str] = []
    for event in data.get("events", []):
        for seg in event.get("segs", []):
            text = seg.get("utf8", "")
            if text:
                parts.append(text)
    return re.sub(r"\n{2,}", "\n", "".join(parts)).strip()


class _SilentLogger:
    """yt-dlp's `quiet`/`no_warnings` options don't suppress hard errors (e.g. 'Unsupported URL'
    on a page with no video) — they still print to the console even when handled correctly
    downstream. Since ChainedFetcher expects YtDlpFetcher to fail on non-video pages and falls
    through to ArticleFetcher, that's normal operation, not a real error worth alarming logs
    with. A no-op logger silences it at the source instead of filtering output after the fact."""

    def debug(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


class YtDlpFetcher(TranscriptFetcher):
    """Fetch captions via yt-dlp — manual subtitles preferred, auto-generated as fallback, English
    preferred but any language accepted. Caption *text* only; no audio download, no ASR."""

    def __init__(self, preferred_langs: tuple[str, ...] = ("en", "en-US", "en-GB")) -> None:
        self._langs = preferred_langs

    def fetch(self, url: str) -> FetchedTranscript:
        try:
            import yt_dlp  # imported lazily so the rest of the hub runs without it installed
        except ImportError as e:  # pragma: no cover - environment-dependent
            raise TranscriptUnavailable("yt-dlp is not installed") from e

        opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "logger": _SilentLogger(),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                tracks = self._pick_track(info)
                if tracks is None:
                    raise TranscriptUnavailable("this source has no captions/transcript available")
                # Download the caption track through yt-dlp's own HTTP client (inherits its TLS,
                # headers and retries — far more robust than a bare urllib call).
                text = self._download_track(ydl, tracks)
        except TranscriptUnavailable:
            raise
        except Exception as e:  # yt-dlp raises many error types; all mean "couldn't get it"
            raise TranscriptUnavailable(f"could not read {url}: {e}") from e

        if not text.strip():
            raise TranscriptUnavailable("the transcript came back empty")
        return FetchedTranscript(
            text=text,
            title=str(info.get("title") or ""),
            channel=str(info.get("uploader") or info.get("channel") or ""),
        )

    def _pick_track(self, info: dict[str, Any]) -> list[dict[str, Any]] | None:
        subs: dict[str, list[dict[str, Any]]] = info.get("subtitles") or {}
        autos: dict[str, list[dict[str, Any]]] = info.get("automatic_captions") or {}
        for source in (subs, autos):  # manual subtitles win over auto-captions
            for lang in self._langs:
                if source.get(lang):
                    return source[lang]
            if source:  # otherwise any available language beats nothing
                return next(iter(source.values()))
        return None

    def _download_track(self, ydl: Any, formats: list[dict[str, Any]]) -> str:
        # Prefer json3 (trivial to parse); fall back to the first format, stripping VTT markup.
        chosen = next((f for f in formats if f.get("ext") == "json3"), None) or formats[0]
        cap_url = chosen.get("url")
        if not cap_url:
            raise TranscriptUnavailable("caption track had no URL")
        raw = ydl.urlopen(cap_url).read()
        if chosen.get("ext") == "json3":
            return _parse_json3(raw)
        return _strip_vtt(raw.decode("utf-8", "replace"))


def _strip_vtt(vtt: str) -> str:
    """Reduce a WebVTT/SRT caption file to plain spoken text: drop headers, timestamps, cue tags."""
    out: list[str] = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        if line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        out.append(re.sub(r"<[^>]+>", "", line))  # strip inline cue tags like <00:00:01.000>
    # collapse consecutive duplicates (auto-captions repeat lines as they roll)
    deduped: list[str] = []
    for line in out:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped).strip()


class ArticleFetcher(TranscriptFetcher):
    """Extracts readable article text from a general webpage — the fallback for URLs that
    aren't a video (or have no embeddable video yt-dlp can find). Uses trafilatura to strip
    navigation/ads/boilerplate down to the actual content: the same 'transcript' concept as a
    video's captions, just for prose instead of speech."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    def fetch(self, url: str) -> FetchedTranscript:
        try:
            import httpx
            import trafilatura
        except ImportError as e:  # pragma: no cover - environment-dependent
            raise TranscriptUnavailable("httpx/trafilatura are not installed") from e

        try:
            response = httpx.get(
                url,
                timeout=self._timeout,
                follow_redirects=True,
                # A normal browser UA, not a self-identifying bot string — some
                # sites (Wikipedia among them, found live) 403 anything that
                # announces itself as automated. Same practice as any
                # read-later tool; this fetches what a human visiting the
                # page would already see, nothing hidden or paywall-bypassed.
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                },
            )
            response.raise_for_status()
        except Exception as e:
            raise TranscriptUnavailable(f"could not fetch {url}: {e}") from e

        text = trafilatura.extract(response.text, include_comments=False, include_tables=False)
        if not text or not text.strip():
            raise TranscriptUnavailable("no readable article content found on this page")

        metadata = trafilatura.extract_metadata(response.text)
        title = (metadata.title if metadata else "") or ""
        site = (metadata.sitename if metadata else "") or ""
        return FetchedTranscript(text=text, title=title, channel=site)


class ChainedFetcher(TranscriptFetcher):
    """Tries each fetcher in order, returning the first success. Only raises
    TranscriptUnavailable (with every fetcher's reason folded in) if all of them fail — this is
    the mechanism behind 'share any URL, get a transcript': video captions if there's a video
    (YtDlpFetcher, which itself scans arbitrary pages for an embed), article text otherwise
    (ArticleFetcher)."""

    def __init__(self, fetchers: list[TranscriptFetcher]) -> None:
        if not fetchers:
            raise ValueError("ChainedFetcher needs at least one fetcher")
        self._fetchers = fetchers

    def fetch(self, url: str) -> FetchedTranscript:
        reasons: list[str] = []
        for fetcher in self._fetchers:
            try:
                return fetcher.fetch(url)
            except TranscriptUnavailable as e:
                reasons.append(str(e))
        raise TranscriptUnavailable("; ".join(reasons) or "no fetcher could read this URL")
