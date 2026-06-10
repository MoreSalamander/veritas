"""The Software Studio — the first organization.

Phase 1 capability: a natural-language goal becomes a single Python function whose
behavior is pinned by an executable spec and verified by deterministic gates.
"""

from orgs.software_studio.module import ModuleResult, build_module
from orgs.software_studio.pipeline import StudioResult, build_function, build_software

__all__ = ["StudioResult", "build_function", "build_software", "ModuleResult", "build_module"]
