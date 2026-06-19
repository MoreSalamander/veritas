"""estimate_tokens — the first component Veritas built for itself.

The bootstrap, made concrete. This function was PROPOSED by the Software Studio org from the
goal "estimate how many LLM tokens are in a string", and ACCEPTED only after clearing the org's
own hard gates: syntax, the oracle-free property gate (it chose `non_negative` and
`monotonic-increasing` — relations it must satisfy regardless of the exact number), the security
scan, and validation. No human read the code and judged it correct; the gates did. Integration
(this file + the wiring) is the human step — the *verification* was the system's. The tool built
a piece of the tool, and the trust invariant held under self-reference.

Build provenance: Software Studio · model claude-sonnet-4-6 · 0 retries · all hard gates passed.
The verified properties are re-asserted as tests in tests/test_tokens.py, so the gate's checks
live on in the suite.
"""

from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)
