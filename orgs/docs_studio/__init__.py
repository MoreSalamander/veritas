"""The Docs Studio — the second organization, on the unchanged engine.

Capability: a topic becomes a technical explainer document whose code examples are
*verified to actually run*. Different domain, different cast, different domain gates —
same Artifact / Gate / Memory / Run / Executor / Validation substrate. This org is the
proof that the framework is reusable and only the cast changes.
"""

from orgs.docs_studio.pipeline import DocsResult, build_doc

__all__ = ["DocsResult", "build_doc"]
