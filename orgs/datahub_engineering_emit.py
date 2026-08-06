"""Stage 2 (Engineering Metadata) emitter: publishes the real engineering
assets behind this platform as DataHub entities — repos, API endpoints,
packages, containers, infrastructure, ML models, prompt templates, and the
CI pipeline. Every entity here corresponds to something that actually
exists and was verified before writing this module (see NOT CATALOGED
below for the honest exceptions).

Uses DataHub's native entity types where they exist rather than forcing
everything into a generic Dataset: MLModel for model routing configs
(MLModelPropertiesClass is purpose-built for this), DataFlow/DataJob for
the CI pipeline (DataHub's own pipeline/orchestration model). Repos, APIs,
packages, containers, and infra components have no equally specific native
type in DataHub's classic model, so they're Dataset entities distinguished
by platform + subType — the conventional way real-world DataHub
deployments catalog these, not an invented workaround.

NOT CATALOGED, and why (verified before writing, not assumed):
- Vector databases: no dedicated indexed vector store exists anywhere in
  this stack. engine/embed.py's Embedder/OllamaEmbedder generates real
  embeddings, but MemoryStore caches them in a plain dict
  (`self._embed_cache`), not a real vector index. Emitting a "vector
  database" entity for that would overclaim what's actually there.
- Feature stores: not an applicable concept — this system doesn't train
  models, it calls hosted/local LLMs. Forcing an MLFeatureTable entity to
  exist here would be fabrication, not cataloging.
- Model checkpoints: same reason — no self-hosted fine-tuned model weights
  anywhere in this stack, only API/Ollama-hosted models (which the MLModel
  entities below already cover as model *routing*, not checkpoints).
"""

from __future__ import annotations

import os
import sys

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DataFlowInfoClass,
    DataJobInfoClass,
    DatasetPropertiesClass,
    MLModelPropertiesClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SubTypesClass,
)

GMS_SERVER = os.environ.get("DATAHUB_GMS", "http://localhost:8080")
PLATFORM = "veritas"
OWNER_URN = "urn:li:corpGroup:veritas-engineering"


def _emit(emitter: DatahubRestEmitter, urn: str, aspect) -> None:
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def _ownership() -> OwnershipClass:
    return OwnershipClass(owners=[OwnerClass(owner=OWNER_URN, type=OwnershipTypeClass.DATAOWNER)])


# --- Source code repositories (real GitHub repos, verified via `git remote get-url origin`) ---

_REPOSITORIES = {
    "veritas": "https://github.com/MoreSalamander/veritas.git",
    "myaistro": "https://github.com/MoreSalamander/myAIstro.git",
    "crypto-hunter": "https://github.com/MoreSalamander/crypto-hunter.git",
    "build-it": "https://github.com/MoreSalamander/build-it.git",
}


def _emit_repositories(emitter: DatahubRestEmitter) -> list[str]:
    urns = []
    for name, url in _REPOSITORIES.items():
        urn = f"urn:li:dataset:(urn:li:dataPlatform:github,{name},PROD)"
        urns.append(urn)
        _emit(emitter, urn, DatasetPropertiesClass(name=name, externalUrl=url))
        _emit(emitter, urn, SubTypesClass(typeNames=["Repository"]))
        _emit(emitter, urn, _ownership())
    return urns


# --- API endpoints (introspected from the real, running FastAPI app — not hand-picked) ---


def _emit_api_endpoints(
    emitter: DatahubRestEmitter,
    fastapi_app: object | None = None,
    route_description: str = "Real Entropy OS front-door FastAPI route.",
) -> list[str]:
    """Catalog a real FastAPI app's route surface as APIEndpoint entities.

    The app is a parameter because the web surface no longer has to live in
    this repo: the front door (entropy-os) passes its own app in. When no app
    is given, the legacy in-repo hub is attempted for as long as it exists —
    and when it doesn't, this stage skips honestly rather than inventing an
    API surface it can't see."""
    if fastapi_app is None:
        try:
            # Local import: avoid requiring a live DB/etc. at module import time,
            # and tolerate the hub's planned removal from this repo entirely.
            from hub.app import app as fastapi_app  # type: ignore[no-redef]
        except Exception:
            print("api-endpoints: no FastAPI app available here — skipped (pass one in)", file=sys.stderr)
            return []

    urns = []
    for route in fastapi_app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for method in sorted(methods):
            if method == "HEAD":
                continue
            name = f"{method}-{path}".replace("/", "_").replace("{", "").replace("}", "")
            urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},api{name},PROD)"
            urns.append(urn)
            _emit(
                emitter,
                urn,
                DatasetPropertiesClass(name=f"{method} {path}", description=route_description),
            )
            _emit(emitter, urn, SubTypesClass(typeNames=["APIEndpoint"]))
            _emit(emitter, urn, _ownership())
    return urns


# --- Python packages (this repo's own installable packages, per pyproject.toml) ---

_PACKAGES = {
    "veritas": "The engine — reliable autonomous organizations (this repo, per pyproject.toml).",
    "hunter_engine": "Shared package across crypto/collectible/free-money Hunter engines — the DataHub-shaped store + scaffold gate they all import.",
}


def _emit_packages(emitter: DatahubRestEmitter) -> list[str]:
    urns = []
    for name, description in _PACKAGES.items():
        urn = f"urn:li:dataset:(urn:li:dataPlatform:pypi,{name},PROD)"
        urns.append(urn)
        _emit(emitter, urn, DatasetPropertiesClass(name=name, description=description))
        _emit(emitter, urn, SubTypesClass(typeNames=["Package"]))
        _emit(emitter, urn, _ownership())
    return urns


# --- Docker containers (real Dockerfiles that exist in this repo) ---

_CONTAINERS = {
    "veritas-fly": "deploy/fly/Dockerfile — the hosted wedge on Fly.io.",
    "veritas-local": "deploy/local/Dockerfile — in-house Docker setup for local deployment.",
}


def _emit_containers(emitter: DatahubRestEmitter) -> list[str]:
    urns = []
    for name, description in _CONTAINERS.items():
        urn = f"urn:li:dataset:(urn:li:dataPlatform:docker,{name},PROD)"
        urns.append(urn)
        _emit(emitter, urn, DatasetPropertiesClass(name=name, description=description))
        _emit(emitter, urn, SubTypesClass(typeNames=["Container"]))
        _emit(emitter, urn, _ownership())
    return urns


# --- Infrastructure components (real, live-verified this session) ---

_INFRA = {
    "veritas-fly-deployment": ("fly", "Hosted wedge deployment, deploy/fly/fly.toml (veritas-dynamics-software.fly.dev)."),
    "veritas-tailscale-serve": ("tailscale", "Tailscale Serve proxy exposing the local hub on the tailnet (kevins-macbook-pro.tailcb963c.ts.net:8099), verified live this session."),
    "veritas-hub-launchd": ("launchd", "com.moresalamander.veritashub LaunchAgent — auto-starts/restarts the hub, verified live this session."),
}


def _emit_infrastructure(emitter: DatahubRestEmitter) -> list[str]:
    urns = []
    for name, (platform, description) in _INFRA.items():
        urn = f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},PROD)"
        urns.append(urn)
        _emit(emitter, urn, DatasetPropertiesClass(name=name, description=description))
        _emit(emitter, urn, SubTypesClass(typeNames=["Infrastructure"]))
        _emit(emitter, urn, _ownership())
    return urns


# --- ML models (DataHub's native MLModel entity — the real routing config from bench/run_bench.py) ---

_MODELS = {
    "gemma-12b": "OllamaProvider, gemma4:12b, no thinking mode.",
    "gemma-12b-think": "OllamaProvider, gemma4:12b, thinking mode.",
    "llama-8b": "OllamaProvider, llama3.1:8b.",
    "qwen-64k-think": "OllamaProvider, qwen3.5-64k, thinking mode.",
    "qwen-coder-14b": "LMStudioProvider, qwen/qwen2.5-coder-14b, local (localhost:1234).",
    "gpt-oss-20b": "LMStudioProvider, gpt-oss-20b-mlx, low reasoning effort.",
    "sonnet": "ClaudeProvider, claude-sonnet-4-6 — the one cloud/hosted option, costs a few cents/build.",
}


def _emit_models(emitter: DatahubRestEmitter) -> list[str]:
    urns = []
    for name, description in _MODELS.items():
        urn = f"urn:li:mlModel:(urn:li:dataPlatform:{PLATFORM},{name},PROD)"
        urns.append(urn)
        _emit(
            emitter,
            urn,
            MLModelPropertiesClass(name=name, description=description, type="proposer"),
        )
        _emit(emitter, urn, _ownership())
    return urns


# --- Prompt templates (real prompt-construction functions, not example text) ---

_PROMPTS = {
    "research-corpus-prompt": "orgs/research_studio/agents.py:corpus_prompt() — builds the Researcher agent's prompt from a topic + pinned Corpus.",
}


def _emit_prompts(emitter: DatahubRestEmitter) -> list[str]:
    urns = []
    for name, description in _PROMPTS.items():
        urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},prompt-{name},PROD)"
        urns.append(urn)
        _emit(emitter, urn, DatasetPropertiesClass(name=name, description=description))
        _emit(emitter, urn, SubTypesClass(typeNames=["PromptTemplate"]))
        _emit(emitter, urn, _ownership())
    return urns


# --- CI/CD pipeline (DataFlow/DataJob — DataHub's native pipeline model; the workflow itself
# is new, written alongside this module since none existed anywhere in the stack before) ---


def _emit_ci_pipeline(emitter: DatahubRestEmitter) -> str:
    flow_urn = "urn:li:dataFlow:(github_actions,veritas_tests,PROD)"
    _emit(
        emitter,
        flow_urn,
        DataFlowInfoClass(
            name="veritas tests",
            description=".github/workflows/tests.yml — runs pytest on every push/PR to main.",
            project="veritas",
        ),
    )
    _emit(emitter, flow_urn, _ownership())

    job_urn = f"urn:li:dataJob:({flow_urn},pytest)"
    _emit(
        emitter,
        job_urn,
        DataJobInfoClass(name="pytest", type="COMMAND", description="pytest -q against the full suite."),
    )
    _emit(emitter, job_urn, _ownership())
    return flow_urn


def emit_all(gms_server: str = GMS_SERVER) -> dict[str, list[str]]:
    """Publish every real engineering asset. Returns {category: [urns]}."""
    emitter = DatahubRestEmitter(gms_server=gms_server)
    try:
        return {
            "repositories": _emit_repositories(emitter),
            "api_endpoints": _emit_api_endpoints(emitter),
            "packages": _emit_packages(emitter),
            "containers": _emit_containers(emitter),
            "infrastructure": _emit_infrastructure(emitter),
            "models": _emit_models(emitter),
            "prompts": _emit_prompts(emitter),
            "ci_pipeline": [_emit_ci_pipeline(emitter)],
        }
    finally:
        emitter.close()


if __name__ == "__main__":
    import sys

    results = emit_all()
    total = sum(len(v) for v in results.values())
    print(f"emitted {total} engineering entities across {len(results)} categories", file=sys.stderr)
    for category, urns in results.items():
        print(f"  {category}: {len(urns)}", file=sys.stderr)
