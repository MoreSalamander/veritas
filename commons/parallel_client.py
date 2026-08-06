"""Live web search + extraction for the Knowledge Graph — Parallel's Search and Extract APIs
(docs.parallel.ai), the seam that lets Veritas go FIND a source itself instead of only ever
answering from whatever a human already pasted in. This is what "accurate, fresh, traceable" (the
phrase that started this) actually buys: a query in, a real fetched page out.

Swappable and offline-testable exactly like TranscriptFetcher (hub/ingest.py): an ABC, one real
HTTP implementation, and a ScriptedSearchClient for tests that never touch the network. What this
module does NOT decide is trust — it only fetches. Whether the fetched content is honest enough to
enter the commons (and under which tag) is engine/memory.py's `from_machine_fetched_source` and
`persist`'s P28c containment; this module hands them real, fetched (url, content) pairs, nothing more.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import certifi

# python.org's macOS Python build doesn't ship a usable system CA bundle for urllib's default SSL
# context — verified live: a request to a real HTTPS host raised CERTIFICATE_VERIFY_FAILED /
# "unable to get local issuer certificate" even though curl and the `anthropic` SDK (httpx, which
# bundles certifi itself) both worked fine from the same machine. Building the context from
# certifi explicitly makes this robust to the host's system cert store instead of depending on it.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class ParallelUnavailable(Exception):
    """Raised when a search or extract call fails — no API key, network error, empty/bad response.
    The caller fails honestly (a clear message, nothing junk persisted) — the same 'fail honestly'
    contract TranscriptUnavailable holds for the existing paste-a-URL ingestion path."""


@dataclass
class SearchResult:
    url: str
    title: str = ""
    publish_date: str | None = None
    excerpts: list[str] = field(default_factory=list)


@dataclass
class ExtractResult:
    url: str
    title: str = ""
    publish_date: str | None = None
    content: str = ""  # full page markdown when available, else the joined search excerpts


class SearchClient(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Ranked URLs + excerpts for `query`. Never raises for zero results — an empty list is a
        legitimate, honest answer; only a transport/auth failure raises ParallelUnavailable."""

    @abstractmethod
    def extract(self, url: str, objective: str = "") -> ExtractResult:
        """Full content at `url`. Raises ParallelUnavailable if the URL can't be fetched or comes
        back empty — never returns a record with nothing in it for a caller to accidentally persist."""


class ScriptedSearchClient(SearchClient):
    """Offline fake for tests: canned search results by query, canned extractions by URL. An
    unscripted query returns no results (search never raises for "nothing found"); an unscripted
    URL raises ParallelUnavailable (extract DOES raise — a caller asked for a specific page and
    nothing came back, which is the real failure mode this class exists to make testable)."""

    def __init__(
        self,
        search_by_query: dict[str, list[SearchResult]] | None = None,
        extract_by_url: dict[str, ExtractResult] | None = None,
    ) -> None:
        self._search = search_by_query or {}
        self._extract = extract_by_url or {}

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return list(self._search.get(query, []))[:max_results]

    def extract(self, url: str, objective: str = "") -> ExtractResult:
        if url not in self._extract:
            raise ParallelUnavailable(f"no scripted extraction for {url!r}")
        return self._extract[url]


class ParallelClient(SearchClient):
    """The real implementation, over Parallel's REST API. Stdlib-only (urllib), matching
    OllamaProvider's transport style in engine/model.py — two POST calls don't earn a new
    dependency. Reads PARALLEL_API_KEY from the environment unless a key is passed explicitly."""

    def __init__(
        self, api_key: str | None = None, host: str = "https://api.parallel.ai", timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("PARALLEL_API_KEY", "")
        self.host = host.rstrip("/")
        self.timeout = timeout

    @classmethod
    def available(cls) -> bool:
        """A key is configured — checked before any org relies on live web search, the same way
        ContainerExecutor.available() and docker_available() gate on their own preconditions."""
        return bool(os.environ.get("PARALLEL_API_KEY"))

    def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        if not self.api_key:
            raise ParallelUnavailable("PARALLEL_API_KEY is not set")
        request = urllib.request.Request(
            f"{self.host}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-api-key": self.api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_SSL_CONTEXT) as response:
                payload: dict[str, object] = json.loads(response.read().decode("utf-8"))
                return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ParallelUnavailable(f"Parallel request to {path} failed: {exc}") from exc

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        data = self._post("/v1/search", {
            "search_queries": [query],
            "advanced_settings": {"max_results": max_results},
        })
        results = data.get("results")
        if not isinstance(results, list):
            return []
        return [
            SearchResult(
                url=str(r.get("url", "")),
                title=str(r.get("title") or ""),
                publish_date=r.get("publish_date"),
                excerpts=[str(e) for e in (r.get("excerpts") or [])],
            )
            for r in results
        ]

    def extract(self, url: str, objective: str = "") -> ExtractResult:
        # No `full_content` field — verified live against the real API, which rejects it outright
        # ("extra_forbidden"); the docs page that mentioned it was wrong or describes a since-
        # changed contract. `excerpts` (objective-focused markdown chunks) is what's actually
        # returned, and per-URL failures land in a separate `errors` array, not silently dropped
        # from `results` — a 403 from a scrape-blocking site is a real, distinct failure worth its
        # own message, not indistinguishable from "nothing came back."
        data = self._post("/v1/extract", {"urls": [url], "objective": objective})
        results = data.get("results")
        if isinstance(results, list) and results:
            r = results[0]
            content = "\n\n".join(str(e) for e in (r.get("excerpts") or []))
            if content.strip():
                return ExtractResult(
                    url=str(r.get("url", url)), title=str(r.get("title") or ""),
                    publish_date=r.get("publish_date"), content=content,
                )
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            detail = errors[0]
            reason = detail.get("error_type", "unknown error")
            status = detail.get("http_status_code")
            raise ParallelUnavailable(
                f"Parallel could not extract {url}: {reason}" + (f" (HTTP {status})" if status else "")
            )
        raise ParallelUnavailable(f"Parallel returned no extraction for {url}")
