"""The intake agent — Veritas's one front desk for work orders from Entropy OS.

The boundary between the operating layer and the engine room, made explicit:
Entropy submits a WorkOrder; this module directs it to the proper engine and
returns the FinishedWork for viewing. Both modes are first-class:

  NAMED    — the order names its engine (the interview or UI already settled
             it); the intake validates and dispatches, no model involved.
  UNNAMED  — a model proposes the engine and a concise goal from the request
             (house doctrine: the model proposes, a deterministic keyword
             table is the fallback, and an unknown-org proposal is rejected
             deterministically — routing is a proposal, the gates downstream
             are still the authority).

Moved here from the front door's own route handler when the repos split the
other way: which engine a request belongs to is engine-room knowledge; what
to do with the answer is the front door's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from engine.catalog import DEFAULT_MODEL, MODELS
from engine.memory import MemoryStore
from engine.model import ModelProvider
from orgs.registry import REGISTRY, OrgRun, get_org


class DispatchError(ValueError):
    """A work order the engine room must refuse at the front desk — unknown
    engine or unknown model. Deterministic, never a model's call."""


# Deterministic routing fallback: first keyword family that matches wins;
# plain software work is the safe default.
_ROUTE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("video", "film", "animation", "movie", "trailer", "narrat", "explainer"), "production"),
    (("lesson", "teach", "course", "curriculum", "学"), "education"),
    (("article", "news", "newsroom", "story about"), "newsroom"),
    (("report", "grounded", "cite", "sources", "summari"), "research"),
    (("experiment", "hypothesis", "benchmark", "reproduc", "outperform", "whether", " beat "), "empirical"),
    (("startup", "mvp", "business", "profitable"), "startup"),
    (("roguelike", "game ", "rpg", "platformer"), "game"),
    (("page", "website", "landing", "site", "html", "dashboard", "ui "), "web"),
    (("function", "code", "module", "algorithm", "program", "script", "app "), "software"),
]


def _keyword_route(request: str) -> str:
    r = f" {request.lower()} "
    for kws, org in _ROUTE_KEYWORDS:
        if any(k in r for k in kws):
            return org
    return "software"


@dataclass(frozen=True)
class WorkOrder:
    """What Entropy OS hands the engine room. `org` names the engine when the
    operating layer already settled it; `goal` defaults to the raw request."""

    request: str
    org: str | None = None
    goal: str | None = None
    model: str = DEFAULT_MODEL
    sources: list[str] | None = None


@dataclass(frozen=True)
class RouteProposal:
    org: str
    goal: str
    proposed_by: Literal["named", "model", "keyword"]


@dataclass(frozen=True)
class FinishedWork:
    """What comes back up to Entropy OS for viewing."""

    order: WorkOrder
    proposal: RouteProposal
    run: OrgRun


def propose_route(request: str, provider: ModelProvider) -> RouteProposal:
    """A model proposes the engine and a concise goal; the deterministic
    keyword table is the fallback; a proposal naming an unknown org is
    discarded deterministically."""
    studios = "; ".join(f"{o.name} = {o.description}" for o in REGISTRY.values())
    system = (
        "You route a user's request to exactly one studio, and extract a concise goal for it. "
        f"Studios: {studios}. Reply with ONLY JSON: "
        "{\"org\": \"<studio name>\", \"goal\": \"<a concise goal/brief for that studio>\"}."
    )
    try:
        raw = provider.propose(role="router", prompt=request, system=system)
        start, end = raw.find("{"), raw.rfind("}")
        obj: dict[str, Any] = json.loads(raw[start:end + 1]) if 0 <= start < end else {}
        cand = str(obj.get("org", "")).strip()
        if cand in REGISTRY:
            return RouteProposal(
                org=cand,
                goal=str(obj.get("goal") or request).strip(),
                proposed_by="model",
            )
    except Exception:  # model down / parse failure -> deterministic fallback
        pass
    return RouteProposal(org=_keyword_route(request), goal=request.strip(), proposed_by="keyword")


def validate_order(order: WorkOrder) -> None:
    """The deterministic front-desk checks. needs_sources stays advisory —
    research runs with an empty corpus today, and the gates downstream are
    the authority on what an empty corpus is worth."""
    if order.org is not None and order.org not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise DispatchError(f"unknown engine {order.org!r} (registered: {known})")
    if order.model not in MODELS:
        known = ", ".join(sorted(MODELS))
        raise DispatchError(f"unknown model {order.model!r} (catalog: {known})")


def dispatch(order: WorkOrder, provider: ModelProvider, memory: MemoryStore) -> FinishedWork:
    """Take the order, direct it to the proper engine, return the finished
    work. Named orders short-circuit routing entirely."""
    validate_order(order)
    if order.org is not None:
        proposal = RouteProposal(
            org=order.org, goal=(order.goal or order.request).strip(), proposed_by="named"
        )
    else:
        proposal = propose_route(order.request, provider)
    run = get_org(proposal.org).build(proposal.goal, provider, memory, sources=order.sources)
    return FinishedWork(order=order, proposal=proposal, run=run)
