"""The verified properties of estimate_tokens, carried from the bootstrap gate into the suite.

estimate_tokens was built by the Software Studio org and accepted by its property gate on
exactly these relations (non_negative + monotonic-increasing) plus exact cases. Re-asserting
them here means the org's verification is now a permanent guard on the integrated component.
"""

from __future__ import annotations

from engine.tokens import estimate_tokens

_STRINGS = ["", "a", "abcd", "Hello, world!", "The quick brown fox jumps over the lazy dog", "x" * 200]


def test_empty_is_zero():
    assert estimate_tokens("") == 0


def test_known_cases():
    assert estimate_tokens("abcd") == 1               # 4 chars / 4
    assert estimate_tokens("Hello, world!") == 4      # 13 -> ceil(13/4)
    assert estimate_tokens("The quick brown fox jumps over the lazy dog") == 11  # 43 -> ceil(43/4)


def test_non_negative():  # the org's first oracle-free property
    assert all(estimate_tokens(s) >= 0 for s in _STRINGS)


def test_monotonic_in_length():  # the org's second oracle-free property
    by_len = sorted(_STRINGS, key=len)
    counts = [estimate_tokens(s) for s in by_len]
    assert all(counts[i] <= counts[i + 1] for i in range(len(counts) - 1))
