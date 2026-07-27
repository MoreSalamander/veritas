"""Veritas's own DataHub — the collection point every other engine's DataHub feeds into.

Not a new copy of each domain's own spec: a generic `EntropyRecord` envelope, admitted (or
held for a human) by a structural gate one recursive level up from each engine's own local
gate — see `collector/gate.py`. Onboarding a new source is one entry in
`config/collector_sources.json`, not a code change; see `collector/sources.py`.
"""

from __future__ import annotations
