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

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from engine.executor import sandbox_active
from engine.memory import MemoryStore, default_memory_store
from engine.model import ModelProvider
from commons.parallel_client import ParallelUnavailable, SearchClient
from orgs.registry import get_org
from orgs.research_studio.report import ReportParseError, parse_report, render_markdown
from orgs.software_studio.pipeline import build_function

# A tenant id becomes a directory name, so it must be path-safe by construction (no separators, no
# traversal). Tokens are operator-defined, but we validate anyway — defense in depth.
_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class Unauthorized(Exception):
    """Missing or unrecognized bearer token — the request has no tenant identity."""


class SourcesUnavailable(Exception):
    """The research slot was asked to research with no live-search client and
    no pasted sources — refused honestly rather than degraded into a
    hallucination engine."""


class OrgNotVendable(Exception):
    """The requested slot isn't on the machine. Deterministic allowlist — a
    stranger can only run the orgs the operator chose to vend."""


# The made-to-order slots: looks right (web), cited right (research), runs
# right (software) — and site: a whole website, looks right TOGETHER (the
# design agency: brief, design corpus, synthesis with provenance, one wall
# per page, site gates across them). Everything else stays operator-only.
VENDABLE_ORGS = ("software", "web", "research", "site")


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
    spec: dict[str, Any] | None = None  # the contract extracted from the goal BEFORE any code — the "why"
    evidence: list[dict[str, Any]] = field(default_factory=list)  # the gate verdicts behind the decision
    remaining: int | None = None  # runs left in the tenant's window, when a meter is attached
    org: str = "software"   # which slot vended this
    artifacts: list[dict[str, Any]] = field(default_factory=list)  # what dropped into the tray


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
        unlimited_check: Callable[[str], bool] | None = None,
        search_client: "SearchClient | None" = None,
    ) -> None:
        self.base = Path(base)
        self.provider_factory = provider_factory
        self.auth = auth
        # Injectable so tests can assert the fail-closed contract without a Docker daemon, and so a
        # future executor-injection can tighten the promise. Default is the live sandbox check.
        self.sandbox_check = sandbox_check
        self.memory_factory = memory_factory
        self.meter = meter  # None => unlimited (local); a QuotaStore => metered (hosted)
        # Returns True for tenants exempt from the quota (owner / unlimited accounts) — they skip the meter.
        self.unlimited_check = unlimited_check
        # The live-research seam: when set, the research slot with no pasted
        # sources FETCHES its own corpus (machine-fetched tier). Without it,
        # empty-sources research is refused — a report grounded in nothing
        # would be a summarizer wearing a lab coat.
        self.search_client = search_client

    def tenant_root(self, tenant: str) -> Path:
        if not _TENANT_RE.match(tenant):  # defense in depth; the token table already validated it
            raise Unauthorized("invalid tenant id")
        return self.base / "tenants" / tenant

    def submit(
        self, *, authorization: str | None, goal: str,
        org: str = "software", sources: list[str] | None = None,
    ) -> WedgeResult:
        """Authenticate → verify isolation is live → run the chosen slot's org in the tenant's own memory.

        Order matters: identity first (no anonymous runs), the slot allowlist and sandbox guard SECOND
        and BEFORE any model-authored code can execute (fail closed), the gated build last. The sandbox
        guard applies to every slot — web and research don't execute stranger code the way software
        does, but one uniform floor is simpler to trust than three special cases."""
        tenant = self.auth.tenant_for(authorization)            # Unauthorized on a bad/absent token
        if org not in VENDABLE_ORGS:
            raise OrgNotVendable(f"slot {org!r} is not on this machine (offered: {', '.join(VENDABLE_ORGS)})")
        if not self.sandbox_check():                            # FAIL CLOSED — no isolation, no run
            raise SandboxUnavailable(
                "execution sandbox is not active; refusing to run untrusted code on the host"
            )
        exempt = self.unlimited_check is not None and self.unlimited_check(tenant)  # owner / unlimited
        if self.meter is not None and not exempt:
            self.meter.check(tenant)                            # QuotaExceeded if over the window's limit
        root = self.tenant_root(tenant)
        if org != "software":
            return self._submit_org_run(tenant, goal, org, sources, root, exempt)
        memory = self.memory_factory(root / "software")         # per-tenant, isolated by path
        result = build_function(goal, self.provider_factory(), memory)
        # The deliverable itself — the code the org wrote and the gates cleared. Without this, "SHIPPED"
        # is a verdict with nothing behind it; with it, the tenant gets the verified function back.
        code = ""
        outcome = getattr(result, "code_outcome", None)
        if outcome is not None and getattr(outcome, "artifact", None) is not None:
            code = outcome.artifact.payload
        # The spec is the contract the org committed to BEFORE writing code — the heart of the thesis
        # ("no synthesis before the constraints are real"). Surfacing it is the behind-the-scenes view.
        spec: dict[str, Any] | None = None
        spec_outcome = getattr(result, "spec_outcome", None)
        if spec_outcome is not None and getattr(spec_outcome, "artifact", None) is not None:
            try:
                loaded = json.loads(spec_outcome.artifact.payload)
                spec = loaded if isinstance(loaded, dict) else None
            except (json.JSONDecodeError, TypeError):
                spec = None
        remaining: int | None = None
        if self.meter is not None and not exempt:
            self.meter.record(tenant, result.accepted, goal)   # the run counts (and is billable)
            remaining = self.meter.remaining(tenant)
        elif exempt:
            remaining = -1  # sentinel: unlimited (the page shows "unlimited" instead of a countdown)
        return WedgeResult(
            tenant=tenant,
            goal=goal,
            accepted=result.accepted,
            run_id=result.run_id,
            isolated=True,
            persisted_at=str(root),
            code=code,
            spec=spec,
            evidence=_evidence(result),
            remaining=remaining,
            org="software",
            artifacts=[{"label": "verified function", "payload": code}] if code else [],
        )

    def _submit_site(
        self, tenant: str, goal: str, root: Path, exempt: bool, memory: MemoryStore,
    ) -> WedgeResult:
        """Vend a whole website: brief -> design corpus -> synthesis ->
        per-page walls -> site gates. The tray holds every page, the design
        system, and the project's context graph."""
        from orgs.web_studio.site import (
            SiteBriefRejected, SiteSynthesisRejected, build_site,
        )

        try:
            site = build_site(
                goal, self.provider_factory(), memory, self.search_client,
                max_pages=3,
            )
        except (SiteBriefRejected, SiteSynthesisRejected) as exc:
            raise SourcesUnavailable(f"the design brief/synthesis was refused: {exc}") from exc

        evidence: list[dict[str, Any]] = []
        for slug, result in site.pages.items():
            outcome = getattr(result, "page_outcome", None) or getattr(result, "spec_outcome", None)
            for gr in getattr(outcome, "gate_results", []) or []:
                evidence.append({
                    "gate": f"{slug}: {gr.gate_name}",
                    "determinism": gr.determinism.value,
                    "passed": gr.passed,
                    "evidence": gr.evidence,
                })
        for g in site.site_gates:
            evidence.append({
                "gate": f"site: {g.gate}", "determinism": "hard",
                "passed": g.passed, "evidence": g.evidence,
            })

        artifacts: list[dict[str, Any]] = [
            {"label": "design brief", "payload": site.brief.brief()},
            {"label": "design system", "payload": site.system.brief()},
        ]
        if site.sources:
            artifacts.append({
                "label": "machine-fetched design sources",
                "payload": "\n".join(f"{s.url}  [{s.angle}]" for s in site.sources),
            })
        for slug in site.brief.pages:
            html = site.page_html(slug)
            if html:
                artifacts.append({"label": f"{slug}.html", "payload": html})
        artifacts.append({
            "label": "context graph",
            "payload": json.dumps(site.context_graph, indent=2),
        })

        remaining: int | None = None
        if self.meter is not None and not exempt:
            self.meter.record(tenant, site.accepted, goal)
            remaining = self.meter.remaining(tenant)
        elif exempt:
            remaining = -1
        return WedgeResult(
            tenant=tenant, goal=goal, accepted=site.accepted,
            run_id=next(iter(site.pages.values())).run_id if site.pages else "site",
            isolated=True, persisted_at=str(root), evidence=evidence,
            remaining=remaining, org="site", artifacts=artifacts,
        )

    def _submit_org_run(
        self, tenant: str, goal: str, org: str, sources: list[str] | None,
        root: Path, exempt: bool,
    ) -> WedgeResult:
        """Vend a non-software slot through the org registry: same tenant
        isolation, same meter, artifacts pulled from every outcome that
        carried one (the web page's HTML, the research report's text)."""
        memory = self.memory_factory(root / org)
        fetched_urls: list[str] = []
        intelligence = None
        if org == "site":
            return self._submit_site(tenant, goal, root, exempt, memory)
        if org == "research" and not sources:
            # REAL research, full intelligence flow: the planner charts the
            # angles, the angle workers acquire in parallel, the researcher
            # extracts claims AND the graph, the same gates rule, and the
            # verified entities persist to this tenant's knowledge layer.
            if self.search_client is None:
                raise SourcesUnavailable(
                    "live research isn't enabled here — paste sources, or the operator sets PARALLEL_API_KEY"
                )
            from orgs.registry import OrgRun
            from orgs.research_studio.pipeline import AcquisitionEmpty, build_intelligence

            try:
                intelligence = build_intelligence(
                    goal, self.provider_factory(), memory, self.search_client,
                )
            except AcquisitionEmpty as exc:
                raise SourcesUnavailable(str(exc)) from exc
            except ParallelUnavailable as exc:
                raise SourcesUnavailable(f"live search failed: {exc}") from exc
            fetched_urls = [f"{s.url}  [{s.angle}]" for s in intelligence.sources]
            rep = intelligence.report
            run = OrgRun(
                org="research", goal=goal, accepted=rep.accepted,
                outcomes=[rep.report_outcome], informed_by=rep.informed_by,
                run_id=rep.run_id, activity=rep.activity,
            )
        else:
            run = get_org(org).build(goal, self.provider_factory(), memory, sources=sources)
        evidence: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        for outcome in run.outcomes:
            for gr in outcome.gate_results:
                evidence.append({
                    "gate": gr.gate_name,
                    "determinism": gr.determinism.value,
                    "passed": gr.passed,
                    "evidence": gr.evidence,
                })
            art = getattr(outcome, "artifact", None)
            if art is not None and getattr(art, "payload", None):
                artifacts.append({"label": getattr(art, "type", "artifact"), "payload": art.payload})
        if org == "research":
            # The report artifact is machine-shaped JSON so the gates can rule
            # exactly; the tray hands over a normal research page rendered
            # from that verified structure. Corpus ids map back to where each
            # source came from (src1, src2, ... in source order). A payload
            # that doesn't parse (a garbled rejected proposal) stays raw and
            # honestly labeled rather than pretending to be a page.
            source_urls: dict[str, str] = {}
            if intelligence is not None:
                # The intelligence flow acquired the corpus itself; ids follow
                # acquisition order, so the map is exact — URL and angle both.
                source_urls = {
                    f"src{i + 1}": f"{src.url} [{src.angle}]"
                    for i, src in enumerate(intelligence.sources)
                }
            for i, s in enumerate(sources or []):
                head = s.strip().split("\n", 1)[0]
                if head.startswith("SOURCE: "):
                    source_urls[f"src{i + 1}"] = head[len("SOURCE: "):].strip()
                elif head.startswith(("http://", "https://")) and " " not in head:
                    source_urls[f"src{i + 1}"] = head
            for entry in artifacts:
                if entry["label"] == "report":
                    try:
                        entry["payload"] = render_markdown(parse_report(entry["payload"]), source_urls)
                        entry["label"] = "grounded report"
                    except ReportParseError:
                        pass
        if fetched_urls:
            artifacts.insert(0, {
                "label": "machine-fetched sources",
                "payload": "\n".join(fetched_urls),
            })
        if intelligence is not None:
            artifacts.insert(0, {"label": "research plan", "payload": intelligence.plan.brief()})
            artifacts.append({
                "label": "context graph",
                "payload": json.dumps(intelligence.context_graph, indent=2),
            })
            # The graph spool: when a DataHub is reachable, the run's context
            # graph is queued for emission into the metadata knowledge graph
            # (the emitter runs under the operator's datahub venv).
            if os.environ.get("DATAHUB_GMS"):
                spool = root.parent / "graph_spool" if (root / "..").exists() else root / "graph_spool"
                spool = (root / "graph_spool")
                spool.mkdir(parents=True, exist_ok=True)
                (spool / f"research-{run.run_id}.json").write_text(
                    json.dumps({"run_id": run.run_id, "tenant": tenant,
                                "graph": intelligence.context_graph}, indent=2),
                    encoding="utf-8",
                )
        remaining: int | None = None
        if self.meter is not None and not exempt:
            self.meter.record(tenant, run.accepted, goal)
            remaining = self.meter.remaining(tenant)
        elif exempt:
            remaining = -1
        return WedgeResult(
            tenant=tenant,
            goal=goal,
            accepted=run.accepted,
            run_id=run.run_id,
            isolated=True,
            persisted_at=str(root),
            evidence=evidence,
            remaining=remaining,
            org=org,
            artifacts=artifacts,
        )
