"""P23 — the embedding seam: recall by meaning, not shared words.

Token-overlap recall misses a past lesson the moment the new goal phrases the same idea
differently ("reverse a list" vs "invert a sequence"). An embedder maps text to a vector so
similarity is semantic. Same seam shape as the model/executor boundaries — a local Ollama
embedder for dev, swappable for hosted. Purely a retrieval upgrade: it changes what the
proposer SEES, never what a gate decides.
"""

from __future__ import annotations

import json
import math
import urllib.request
from abc import ABC, abstractmethod


class Embedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class OllamaEmbedder(Embedder):
    """Local embeddings via Ollama (default nomic-embed-text). Stdlib-only, like OllamaProvider."""

    def __init__(
        self, model: str = "nomic-embed-text", host: str = "http://localhost:11434", timeout: float = 30.0
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def embed(self, text: str) -> list[float]:
        body = {"model": self.model, "prompt": text}
        request = urllib.request.Request(
            f"{self.host}/api/embeddings",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [float(x) for x in payload.get("embedding", [])]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
