"""Stage 7 (Organization-Wide Knowledge Graph) emitter: the real EDGES
between the entities Stages 1-6 already published — turning a catalog of
nodes into a connected graph where impact analysis is a query, not a
guess.

The vision's chain (Project -> Repository -> API -> Dataset -> AI Agent ->
Prompt -> Model -> Deployment -> Documentation -> Tests) maps onto real
relationships that exist in this codebase:

    Project        -> a native DataHub Container ("veritas-project");
                      containment via the `container` aspect
    Repository     -> the github/veritas dataset (Stage 2)
    API            -> every endpoint entity is served FROM the repo's code
                      (hub/app.py) -> upstream edge to the repo
    Dataset        -> org runs/outcomes/opportunities (Stages 3-5) already
                      carry their own lineage from Stage 4
    AI Agent       -> agent entities (Stage 6); each agent's code lives in
                      the repo (orgs/*/agents.py) -> upstream edge
    Prompt         -> prompt template entity (Stage 2), defined in the
                      repo -> upstream edge; the researcher agent CONSUMES
                      it -> agent gets a second upstream edge to the prompt
    Model          -> MLModel entities (Stage 2); linked from execution
                      records via Stage 3's model_invoked on every outcome
                      (dataset-lineage aspects only accept dataset URNs,
                      so the model linkage is property-based by design)
    Deployment     -> infra entities (Stage 2: Fly, launchd, Tailscale),
                      each deployed FROM the repo -> upstream edge
    Documentation  -> docs/ entity (real: docs/index.html, GitHub Pages),
                      built from the repo -> upstream edge
    Tests          -> the CI DataJob (Stage 2) consumes the repo as its
                      input, via DataHub's native DataJobInputOutput

The proof query this enables: downstream lineage from the repo = every
API endpoint, agent, prompt, deployment, and doc that changes when the
repo changes. Impact analysis, automatic.
"""

from __future__ import annotations

import os

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    ContainerClass,
    ContainerPropertiesClass,
    DataJobInputOutputClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    SubTypesClass,
    UpstreamClass,
    UpstreamLineageClass,
)

from orgs.datahub_engineering_emit import _emit_api_endpoints

GMS_SERVER = os.environ.get("DATAHUB_GMS", "http://localhost:8080")
PLATFORM = "veritas"

REPO_URN = "urn:li:dataset:(urn:li:dataPlatform:github,veritas,PROD)"
CONTAINER_URN = "urn:li:container:veritas-project"
DOCS_URN = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},veritas-docs,PROD)"
PROMPT_URN = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},prompt-research-corpus-prompt,PROD)"
CI_JOB_URN = "urn:li:dataJob:(urn:li:dataFlow:(github_actions,veritas_tests,PROD),pytest)"

# Real agents whose code lives in this repo (orgs/*/agents.py) and were
# published by Stage 6 from real run history.
_REPO_AGENTS = ["spec-agent", "developer-agent", "doc-agent", "researcher-agent"]

_INFRA_URNS = [
    "urn:li:dataset:(urn:li:dataPlatform:fly,veritas-fly-deployment,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:launchd,veritas-hub-launchd,PROD)",
    "urn:li:dataset:(urn:li:dataPlatform:tailscale,veritas-tailscale-serve,PROD)",
]


def _emit(emitter: DatahubRestEmitter, urn: str, aspect) -> None:
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def _upstream_repo() -> UpstreamLineageClass:
    return UpstreamLineageClass(
        upstreams=[UpstreamClass(dataset=REPO_URN, type=DatasetLineageTypeClass.TRANSFORMED)]
    )


def emit_graph(gms_server: str = GMS_SERVER) -> dict[str, int]:
    """Emit the project container plus every real cross-entity edge.
    Returns {edge_kind: count} for reporting."""
    emitter = DatahubRestEmitter(gms_server=gms_server)
    counts: dict[str, int] = {}
    try:
        # Project container + membership for the repo-level entities.
        _emit(
            emitter,
            CONTAINER_URN,
            ContainerPropertiesClass(
                name="veritas project",
                description="The whole Veritas project: repo, APIs, agents, prompts, models, deployments, docs, tests.",
            ),
        )
        for urn in [REPO_URN, DOCS_URN, PROMPT_URN]:
            _emit(emitter, urn, ContainerClass(container=CONTAINER_URN))
        counts["container_members"] = 3

        # Documentation entity (real: docs/index.html served via GitHub Pages).
        _emit(
            emitter,
            DOCS_URN,
            DatasetPropertiesClass(
                name="veritas docs",
                description="docs/ — the project's public documentation (GitHub Pages).",
                externalUrl="https://moresalamander.github.io/veritas/",
            ),
        )
        _emit(emitter, DOCS_URN, SubTypesClass(typeNames=["Documentation"]))
        _emit(emitter, DOCS_URN, _upstream_repo())
        counts["docs_edges"] = 1

        # Every API endpoint is served from the repo's code.
        api_urns = _emit_api_endpoints(emitter)
        for urn in api_urns:
            _emit(emitter, urn, _upstream_repo())
        counts["api_edges"] = len(api_urns)

        # Prompt template is defined in the repo; the researcher agent consumes it.
        _emit(emitter, PROMPT_URN, _upstream_repo())
        counts["prompt_edges"] = 1

        # Each agent's code lives in the repo; researcher additionally
        # depends on its prompt template.
        for agent in _REPO_AGENTS:
            agent_urn = f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},agent-{agent},PROD)"
            upstreams = [UpstreamClass(dataset=REPO_URN, type=DatasetLineageTypeClass.TRANSFORMED)]
            if agent == "researcher-agent":
                upstreams.append(
                    UpstreamClass(dataset=PROMPT_URN, type=DatasetLineageTypeClass.TRANSFORMED)
                )
            _emit(emitter, agent_urn, UpstreamLineageClass(upstreams=upstreams))
        counts["agent_edges"] = len(_REPO_AGENTS)

        # Deployments are built from the repo.
        for urn in _INFRA_URNS:
            _emit(emitter, urn, _upstream_repo())
        counts["deployment_edges"] = len(_INFRA_URNS)

        # The CI pytest job consumes the repo — DataHub's native
        # DataJob input/output mechanism, not a dataset-lineage workaround.
        _emit(emitter, CI_JOB_URN, DataJobInputOutputClass(inputDatasets=[REPO_URN], outputDatasets=[]))
        counts["ci_edges"] = 1

        return counts
    finally:
        emitter.close()


if __name__ == "__main__":
    import sys

    counts = emit_graph()
    print(f"emitted graph edges: {counts}", file=sys.stderr)
