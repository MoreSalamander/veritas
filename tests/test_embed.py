"""P23 — semantic recall: find a past lesson even when the wording differs.

Token overlap misses "invert a sequence" against a lesson about "reversing a list" — no shared
words. An embedder ranks by meaning, so it finds it. Proven deterministically with a topic
embedder (the real nomic-embed comparison is a live demo); the plumbing is what's under test.
"""

from __future__ import annotations

from engine.embed import Embedder, cosine
from engine.memory import MemoryRecord, MemoryStore


class TopicEmbedder(Embedder):
    """Deterministic stand-in: maps text to one of three orthogonal 'topic' axes by keyword, so
    paraphrases of the same topic land on the same vector. (Real embeddings do this by meaning.)"""

    def embed(self, text: str) -> list[float]:
        t = text.lower()
        if any(k in t for k in ("revers", "invert", "backward")):
            return [1.0, 0.0, 0.0]
        if any(k in t for k in ("color", "palette", "theme")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def _seed(store: MemoryStore) -> None:
    store.persist(MemoryRecord(category="lesson", title="reversing a list",
                               body="reversing a list returns its elements backward"))
    store.persist(MemoryRecord(category="lesson", title="color palette",
                               body="choosing a tasteful color palette for a theme"))


def test_cosine():
    assert cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine([1, 0, 0], [0, 1, 0]) == 0.0
    assert cosine([], [1.0]) == 0.0


def test_token_overlap_misses_a_paraphrase(tmp_path):
    store = MemoryStore(tmp_path)  # no embedder -> token overlap
    _seed(store)
    assert store.recall("how do I invert a sequence") == []  # different words -> no overlap


def test_semantic_recall_finds_the_paraphrase(tmp_path):
    store = MemoryStore(tmp_path, embedder=TopicEmbedder())
    _seed(store)
    hits = store.recall("how do I invert a sequence", limit=3)
    assert len(hits) == 1 and "reversing" in hits[0].title  # found by meaning; color excluded


def test_embedder_falls_back_to_tokens_when_it_errors(tmp_path):
    class Broken(Embedder):
        def embed(self, text: str) -> list[float]:
            raise RuntimeError("embedder down")

    store = MemoryStore(tmp_path, embedder=Broken())
    _seed(store)
    # query shares a token ("palette") so token-overlap fallback still finds the color lesson
    hits = store.recall("a nice palette")
    assert any("color palette" in h.title for h in hits)
