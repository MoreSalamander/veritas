"""Transcript fetching for the Second Brain (P28b) — a swappable seam, like Executor/Publisher.

The commons stores *text*; this is the one piece that turns a pasted URL into that text. It is
isolated behind an ABC so (a) tests never touch the network (ScriptedFetcher) and (b) the concrete
backend (yt-dlp today, anything later) is a config swap, not a rewrite. The fetcher only retrieves
what a source already says — it never judges it; the `human-vouched` containment lives downstream
in MemoryRecord.from_source.
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

        opts = {"skip_download": True, "quiet": True, "no_warnings": True}
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
