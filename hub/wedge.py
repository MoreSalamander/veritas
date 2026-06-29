"""P31c1 — the hosted wedge: the narrow path by which someone OTHER than the author runs Veritas.

A stranger submits a goal; the Software org runs it ISOLATED (the sandboxed executor from P31a),
PERSISTED (a per-tenant memory from P31b), and GATED (the same verification model the author uses).
The wedge adds exactly the three things a single-user local hub never needed:

  • an IDENTITY — a bearer token maps to a tenant id, so a run is attributable;
  • per-tenant ISOLATION — each tenant's memory lives at its own path, so one tenant can never read
    another's lessons or artifacts;
  • a FAIL-CLOSED guard — if the execution sandbox is not actually active, the run is REFUSED, never
    silently executed on the host. No isolation ⇒ no run. That is the load-bearing safety property.

"Minimal auth" here is the floor that PROVES isolation, not a product: a static token→tenant table.
Real accounts, sessions, rate limits, and billing are P31c2 — none of them change whether the
architecture holds. This module is pure logic (no web framework) so it is unit-testable; the HTTP
endpoints in hub/app.py are a thin shell over `Wedge.submit`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from engine.executor import sandbox_active
from engine.memory import MemoryStore, default_memory_store
from engine.model import ModelProvider
from orgs.software_studio.pipeline import build_function

# A tenant id becomes a directory name, so it must be path-safe by construction (no separators, no
# traversal). Tokens are operator-defined, but we validate anyway — defense in depth.
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class Unauthorized(Exception):
    """Missing or unrecognized bearer token — the request has no tenant identity."""


class SandboxUnavailable(Exception):
    """Isolation is not active, so an untrusted run must NOT proceed. The wedge fails closed."""


class QuotaExceeded(Exception):
    """The tenant has spent its allowance for the current window — the run is refused (HTTP 429)."""


@runtime_checkable
class Meter(Protocol):
    """The metering seam: count a tenant's runs, enforce a ceiling, and report what's left. The same
    ledger a billing system reads. Optional — a local wedge runs without one (unlimited)."""

    def check(self, tenant: str) -> None: ...        # raise QuotaExceeded if over the limit
    def record(self, tenant: str, accepted: bool, goal: str) -> None: ...
    def remaining(self, tenant: str) -> int: ...


@runtime_checkable
class Authenticator(Protocol):
    """The auth seam: turn an `Authorization` header into a tenant id, or raise `Unauthorized`. The
    static `WedgeAuth` (env tokens, P31c1) and the DB-backed `AccountStore` (real accounts, P31c2)
    are interchangeable behind it — the wedge never learns which one it holds."""

    def tenant_for(self, authorization: str | None) -> str: ...


def parse_bearer(authorization: str | None) -> str | None:
    """Pull the raw token out of an `Authorization: Bearer <token>` header (or accept a bare token).
    Shared so every authenticator strips the scheme the same way."""
    if not authorization:
        return None
    header = authorization.strip()
    return header[7:].strip() if header[:7].lower() == "bearer " else header


@dataclass(frozen=True)
class WedgeAuth:
    """A static bearer-token → tenant-id table. The minimal identity floor (P31c1)."""

    tokens: dict[str, str]

    @classmethod
    def from_env(cls, raw: str | None = None) -> "WedgeAuth":
        """Parse VERITAS_WEDGE_TOKENS='tok_a:alice,tok_b:bob'. An EMPTY table means the wedge is
        closed — every request is Unauthorized — which is the safe default for an unconfigured host."""
        raw = raw if raw is not None else os.environ.get("VERITAS_WEDGE_TOKENS", "")
        tokens: dict[str, str] = {}
        for pair in raw.split(","):
            token, _, tenant = pair.strip().partition(":")
            token, tenant = token.strip(), tenant.strip()
            if token and tenant and _TENANT_RE.match(tenant):
                tokens[token] = tenant
        return cls(tokens)

    def tenant_for(self, authorization: str | None) -> str:
        """Map an `Authorization: Bearer <token>` header (or a bare token) to a tenant id, or refuse."""
        token = parse_bearer(authorization)
        if not token:
            raise Unauthorized("missing Authorization header")
        tenant = self.tokens.get(token)
        if not tenant:
            raise Unauthorized("unrecognized token")
        return tenant


@dataclass
class WedgeResult:
    tenant: str
    goal: str
    accepted: bool
    run_id: str
    isolated: bool          # the run executed inside the sandbox
    persisted_at: str       # the tenant's data root — for the operator's audit, never another tenant's
    code: str = ""          # the function the org built (the actual deliverable, shown on SHIPPED)
    evidence: list[dict[str, Any]] = field(default_factory=list)  # the gate verdicts behind the decision
    remaining: int | None = None  # runs left in the tenant's window, when a meter is attached


def _evidence(result: Any) -> list[dict[str, Any]]:
    """The gate trail behind the decision — what was checked and how it fell. This is the wedge's
    honesty: the stranger sees not just accept/reject but the deterministic gates that decided it."""
    outcome = getattr(result, "code_outcome", None) or getattr(result, "spec_outcome", None)
    if outcome is None:
        return []
    return [
        {
            "gate": gr.gate_name,
            "determinism": gr.determinism.value,
            "passed": gr.passed,
            "evidence": gr.evidence,
        }
        for gr in outcome.gate_results
    ]


class Wedge:
    """The hosted submission service. `submit` is the whole public surface."""

    def __init__(
        self,
        base: Path | str,
        provider_factory: Callable[[], ModelProvider],
        auth: Authenticator,
        *,
        sandbox_check: Callable[[], bool] = sandbox_active,
        memory_factory: Callable[[Path], MemoryStore] = default_memory_store,
        meter: Meter | None = None,
    ) -> None:
        self.base = Path(base)
        self.provider_factory = provider_factory
        self.auth = auth
        # Injectable so tests can assert the fail-closed contract without a Docker daemon, and so a
        # future executor-injection can tighten the promise. Default is the live sandbox check.
        self.sandbox_check = sandbox_check
        self.memory_factory = memory_factory
        self.meter = meter  # None => unlimited (local); a QuotaStore => metered (hosted)

    def tenant_root(self, tenant: str) -> Path:
        if not _TENANT_RE.match(tenant):  # defense in depth; the token table already validated it
            raise Unauthorized("invalid tenant id")
        return self.base / "tenants" / tenant

    def submit(self, *, authorization: str | None, goal: str) -> WedgeResult:
        """Authenticate → verify isolation is live → run the Software org in the tenant's own memory.

        Order matters: identity first (no anonymous runs), the sandbox guard SECOND and BEFORE any
        model-authored code can execute (fail closed), the gated build last."""
        tenant = self.auth.tenant_for(authorization)            # Unauthorized on a bad/absent token
        if not self.sandbox_check():                            # FAIL CLOSED — no isolation, no run
            raise SandboxUnavailable(
                "execution sandbox is not active; refusing to run untrusted code on the host"
            )
        if self.meter is not None:
            self.meter.check(tenant)                            # QuotaExceeded if over the window's limit
        root = self.tenant_root(tenant)
        memory = self.memory_factory(root / "software")         # per-tenant, isolated by path
        result = build_function(goal, self.provider_factory(), memory)
        # The deliverable itself — the code the org wrote and the gates cleared. Without this, "SHIPPED"
        # is a verdict with nothing behind it; with it, the tenant gets the verified function back.
        code = ""
        outcome = getattr(result, "code_outcome", None)
        if outcome is not None and getattr(outcome, "artifact", None) is not None:
            code = outcome.artifact.payload
        remaining: int | None = None
        if self.meter is not None:
            self.meter.record(tenant, result.accepted, goal)   # the run counts (and is billable)
            remaining = self.meter.remaining(tenant)
        return WedgeResult(
            tenant=tenant,
            goal=goal,
            accepted=result.accepted,
            run_id=result.run_id,
            isolated=True,
            persisted_at=str(root),
            code=code,
            evidence=_evidence(result),
            remaining=remaining,
        )
