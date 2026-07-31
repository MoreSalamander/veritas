"""Veritas -> DataHub emitter: publishes an OrgRun as a real DataHub dataset
graph — one dataset per org run (the logical parent), one dataset per
outcome (the physical children), real lineage edges between them, and one
custom assertion per outcome carrying its actual gate verdict.

Consumes `orgs.registry.OrgRun` / `engine.run.Outcome` directly — the exact
type `orgs.hunter_engine_bridge.run_hunter_engine()` returns for a real
Hunter engine. `build_toy_org_run()` below constructs the same OrgRun shape
from synthetic data for demos and local testing. Toy and real-domain data
share this one emit path; they differ only in how the OrgRun was built, not
in how it's published to DataHub.

DESIGN NOTE — eager tag/ownership propagation, not DataHub-native. DataHub's
own governance model ("define rich context once on a logical parent, apply
it everywhere it's physically deployed") is implemented as an Actions-
framework action (tag/glossary-term propagation along lineage edges), not as
automatic graph behavior. Verified against a live local instance before
writing this module: tagging an org dataset that already had real lineage
edges to its outcome children did NOT cause the children to inherit the tag
— the propagation action isn't configured in a default `datahub docker
quickstart`. Rather than depend on that, this module writes ownership/tags
once on the org AND again on each outcome at emit time. If the native
propagation action is enabled later, these per-outcome writes become
redundant but harmless (metadata aspects are last-write-wins on re-emit).

DESIGN NOTE — assertions are written as raw metadata aspects, not via
DataHubGraph's upsert_custom_assertion()/report_assertion_result(). Those
methods hardcode a GraphQL mutation that includes a `severity` field; this
local quickstart's GMS build predates that field and rejects the mutation
with "Unknown type 'AssertionResultSeverity'" — a real version skew between
the installed `acryl-datahub` SDK and the running server, verified by
hitting it directly. Aspect emission (AssertionInfo + AssertionRunEvent via
MetadataChangeProposalWrapper, same path as every other aspect in this
module) sidesteps GraphQL entirely and is what upsert_custom_assertion/
report_assertion_result do server-side anyway once the mutation succeeds.

DESIGN NOTE — tags reflect real code, not an invented scheme. Rather than a
standalone numeric "trust tier," each outcome is tagged by the strictest
`engine.artifact.Determinism` among its actual gate results (HARD/SOFT/
HUMAN) — the distinction the gate system already enforces at the type level
(engine/artifact.py: "A SOFT gate must never be presented as a HARD one").
Real Hunter-engine outcomes (orgs/hunter_engine_bridge.py) are always HARD by
construction, since every gate result there comes from the org's own
machine-checkable scaffold gate; `build_toy_org_run()` intentionally mixes
all three so the full tagging path gets exercised in demos.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    AssertionInfoClass,
    AssertionResultClass,
    AssertionResultTypeClass,
    AssertionRunEventClass,
    AssertionRunStatusClass,
    AssertionTypeClass,
    AuditStampClass,
    BooleanTypeClass,
    CustomAssertionInfoClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    GlobalTagsClass,
    GlossaryTermAssociationClass,
    GlossaryTermInfoClass,
    GlossaryTermsClass,
    OtherSchemaClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    TagAssociationClass,
    TagPropertiesClass,
    UpstreamClass,
    UpstreamLineageClass,
)

from engine.artifact import Artifact, Determinism, GateResult
from engine.run import Outcome
from orgs.registry import OrgRun

GMS_SERVER = "http://localhost:8080"
PLATFORM = "veritas"

# The real, code-level rigor distinction (engine/artifact.py Determinism) —
# not an invented tier scheme. Each tag is documented via TagPropertiesClass
# so it's self-explanatory to anyone browsing DataHub, not a bare label.
_DETERMINISM_TAG: dict[Determinism, tuple[str, str]] = {
    Determinism.HARD: (
        "VeritasHardGated",
        "Verdict from a machine-checkable gate (tests, types, schema, scans) — no LLM opinion involved.",
    ),
    Determinism.SOFT: (
        "VeritasSoftJudged",
        "Verdict from a judge-LLM's opinion — recorded, but never disguised as proof.",
    ),
    Determinism.HUMAN: (
        "VeritasHumanApproved",
        "A person signed off — the proper verifier for feel/taste (create mode).",
    ),
}

# Highest-rigor-first: a single soft judgment shouldn't hide behind a hard
# gate that also happened to run on the same outcome.
_DETERMINISM_PRIORITY = [Determinism.HUMAN, Determinism.HARD, Determinism.SOFT]

# The governed glossary term backing each rigor tag (Stage 1 business
# glossary — the tag is the quick-browse label, the term is its definition).
_DETERMINISM_GLOSSARY_TERM = {
    Determinism.HARD: "HardGate",
    Determinism.SOFT: "SoftGate",
    Determinism.HUMAN: "HumanGate",
}

# Stage 1 (Foundation) — business glossary. Tags (above) are informal, ad-hoc
# labels; glossary terms are formal, governed vocabulary with a real
# definition attached — DataHub's own distinction, not a synonym for tags.
# These are the actual domain concepts Veritas's trust model is built on,
# not invented examples. termSource="INTERNAL" because they're defined by
# this organization, not borrowed from an external ontology.
_GLOSSARY_TERMS: dict[str, str] = {
    "Determinism": (
        "Whether a gate's verdict is machine-checkable (HARD) or a judgment "
        "(SOFT) or a human sign-off (HUMAN). A SOFT gate must never be "
        "presented as a HARD one (engine/artifact.py)."
    ),
    "HardGate": "A verdict from a machine-checkable check (tests, types, schema, scans) — no LLM opinion involved.",
    "SoftGate": "A verdict from a judge-LLM's opinion — recorded, but never disguised as proof.",
    "HumanGate": "A verdict from a person signing off — the proper verifier for feel/taste (create mode).",
    "HumanVouchedSource": (
        "A human curated this source (Veritas P28) — vouches for it being worth "
        "keeping, NOT for the truth of its claims. May ground only an attributed "
        "claim, never an asserted fact."
    ),
    "CustomAssertion": "A DataHub assertion for a check that ran OUTSIDE DataHub, with its result reported in.",
}


def _glossary_term_urn(name: str) -> str:
    return f"urn:li:glossaryTerm:{name}"


def _ensure_glossary_terms(emitter: DatahubRestEmitter) -> None:
    """Registers every term in _GLOSSARY_TERMS (idempotent — safe to call on
    every emit_org_run, same pattern as the per-outcome tag registration)."""
    for name, definition in _GLOSSARY_TERMS.items():
        _emit(
            emitter,
            _glossary_term_urn(name),
            GlossaryTermInfoClass(definition=definition, termSource="INTERNAL", name=name),
        )


def _glossary_terms_aspect(*names: str) -> GlossaryTermsClass:
    now_millis = int(datetime.now().timestamp() * 1000)
    return GlossaryTermsClass(
        terms=[GlossaryTermAssociationClass(urn=_glossary_term_urn(n)) for n in names],
        auditStamp=AuditStampClass(time=now_millis, actor="urn:li:corpuser:veritas"),
    )


# Stage 1 (Foundation) — real schema documentation + schema evolution
# monitoring. `version`/`hash` are DataHub's own mechanism for detecting
# schema change over time: re-emitting with a changed hash and incremented
# version is what makes evolution actually trackable, not just present once.
_OUTCOME_SCHEMA_VERSION = 1


def _outcome_schema_metadata(outcome_urn: str) -> SchemaMetadataClass:
    fields = [
        SchemaFieldClass(
            fieldPath="type",
            type=SchemaFieldDataTypeClass(type=StringTypeClass()),
            nativeDataType="string",
            description="The artifact type this outcome represents, e.g. 'opportunity'.",
        ),
        SchemaFieldClass(
            fieldPath="accepted",
            type=SchemaFieldDataTypeClass(type=BooleanTypeClass()),
            nativeDataType="boolean",
            description="Whether the org's gate accepted this outcome — the verdict this dataset's assertion reports.",
        ),
        SchemaFieldClass(
            fieldPath="created_by",
            type=SchemaFieldDataTypeClass(type=StringTypeClass()),
            nativeDataType="string",
            description="Provenance.created_by — who/what produced this artifact.",
        ),
        SchemaFieldClass(
            fieldPath="accepted_because",
            type=SchemaFieldDataTypeClass(type=StringTypeClass()),
            nativeDataType="string",
            description="Provenance.accepted_because — the stated reason the gate accepted this outcome, if it did.",
        ),
    ]
    schema_hash = hashlib.sha256(
        "|".join(f"{f.fieldPath}:{f.nativeDataType}" for f in fields).encode()
    ).hexdigest()[:16]
    return SchemaMetadataClass(
        schemaName=f"{outcome_urn}-schema",
        platform=f"urn:li:dataPlatform:{PLATFORM}",
        version=_OUTCOME_SCHEMA_VERSION,
        hash=schema_hash,
        platformSchema=OtherSchemaClass(rawSchema="veritas.engine.run.Outcome"),
        fields=fields,
    )


def _org_urn(org_run: OrgRun) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{org_run.org}-{org_run.run_id},PROD)"


def _outcome_urn(org_run: OrgRun, index: int) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{org_run.org}-{org_run.run_id}-outcome-{index},PROD)"


def _owner_urn(org_run: OrgRun) -> str:
    """A corpGroup, not a corpUser: the producer is an automated engine, not
    an individual — DataHub's ownership model accepts either actor type."""
    return f"urn:li:corpGroup:veritas-{org_run.org.replace('_', '-')}"


def _rigor_determinism(outcome: Outcome) -> Determinism | None:
    """The strictest Determinism among an outcome's actual gate results, or
    None if it has no gate results to characterize."""
    present = {gr.determinism for gr in outcome.gate_results}
    for determinism in _DETERMINISM_PRIORITY:
        if determinism in present:
            return determinism
    return None


def _millis(iso_timestamp: str) -> int:
    return int(datetime.fromisoformat(iso_timestamp).timestamp() * 1000)


def _emit(emitter: DatahubRestEmitter, urn: str, aspect) -> None:
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def emit_org_run(org_run: OrgRun, gms_server: str = GMS_SERVER) -> dict[int, str]:
    """Publish one OrgRun to a live DataHub instance.

    Returns {outcome_index: dataset_urn}, in case a caller wants to look up
    what was just written (e.g. to cross-check via the DataHub MCP tools).
    """
    emitter = DatahubRestEmitter(gms_server=gms_server)
    try:
        org_urn = _org_urn(org_run)
        owner_urn = _owner_urn(org_run)
        ownership = OwnershipClass(
            owners=[OwnerClass(owner=owner_urn, type=OwnershipTypeClass.DATAOWNER)]
        )

        _emit(
            emitter,
            org_urn,
            DatasetPropertiesClass(
                name=f"{org_run.org} - {org_run.run_id}",
                description=f"Org run for goal: {org_run.goal!r}. "
                f"{len(org_run.outcomes)} outcomes, overall accepted={org_run.accepted}.",
            ),
        )
        _emit(emitter, org_urn, ownership)
        _ensure_glossary_terms(emitter)

        outcome_urns: dict[int, str] = {}
        for index, outcome in enumerate(org_run.outcomes):
            urn = _outcome_urn(org_run, index)
            outcome_urns[index] = urn
            provenance = outcome.artifact.provenance

            _emit(emitter, urn, _outcome_schema_metadata(urn))

            _emit(
                emitter,
                urn,
                DatasetPropertiesClass(
                    name=f"{outcome.artifact.type}-{index}",
                    description=provenance.rationale,
                    customProperties={
                        "created_by": provenance.created_by,
                        "accepted_because": provenance.accepted_because or "",
                    },
                ),
            )
            # Eagerly propagated org-level context — see module docstring.
            _emit(emitter, urn, ownership)
            _emit(
                emitter,
                urn,
                UpstreamLineageClass(
                    upstreams=[
                        UpstreamClass(dataset=org_urn, type=DatasetLineageTypeClass.TRANSFORMED)
                    ]
                ),
            )

            rigor = _rigor_determinism(outcome)
            if rigor is not None:
                tag_name, tag_description = _DETERMINISM_TAG[rigor]
                tag_urn = f"urn:li:tag:{tag_name}"
                _emit(emitter, tag_urn, TagPropertiesClass(name=tag_name, description=tag_description))
                _emit(emitter, urn, GlobalTagsClass(tags=[TagAssociationClass(tag=tag_urn)]))
                # The tag is the quick-browse label; the glossary term is the
                # governed definition behind it (Stage 1 business glossary).
                _emit(emitter, urn, _glossary_terms_aspect(_DETERMINISM_GLOSSARY_TERM[rigor]))

            # One custom assertion per outcome: the S2 recon mapping (gate
            # pass/fail -> DataHub Assertion) applied for real. `logic`
            # records exactly which gates ran and how each one voted.
            assertion_urn = f"urn:li:assertion:{org_run.org}-{org_run.run_id}-outcome-{index}"
            _emit(
                emitter,
                assertion_urn,
                AssertionInfoClass(
                    type=AssertionTypeClass.CUSTOM,
                    customAssertion=CustomAssertionInfoClass(
                        type="VERITAS_GATE",
                        entity=urn,
                        logic="; ".join(f"{gr.gate_name}={gr.passed}" for gr in outcome.gate_results)
                        or None,
                    ),
                    description=f"Veritas gate verdict for outcome {index}: accepted={outcome.accepted}",
                ),
            )
            timestamp_millis = _millis(outcome.artifact.created_at)
            _emit(
                emitter,
                assertion_urn,
                AssertionRunEventClass(
                    timestampMillis=timestamp_millis,
                    runId=f"{org_run.run_id}-outcome-{index}",
                    asserteeUrn=urn,
                    status=AssertionRunStatusClass.COMPLETE,
                    assertionUrn=assertion_urn,
                    result=AssertionResultClass(
                        type=AssertionResultTypeClass.SUCCESS
                        if outcome.accepted
                        else AssertionResultTypeClass.FAILURE,
                        nativeResults={gr.gate_name: str(gr.passed) for gr in outcome.gate_results},
                    ),
                ),
            )
        return outcome_urns
    finally:
        emitter.close()


def build_toy_org_run(org_name: str, run_id: str, num_outcomes: int = 10) -> OrgRun:
    """Synthetic OrgRun for demos/local testing — built from the SAME real
    Artifact/GateResult/Outcome types a live Hunter engine produces, just
    with fabricated payloads instead of a real day-cycle. Deliberately mixes
    all three Determinism values (real Hunter-engine data is HARD-only; see
    module docstring) so a demo run exercises the full tagging path.
    """
    import random
    from pathlib import Path

    determinisms = [Determinism.HARD, Determinism.HARD, Determinism.SOFT, Determinism.HUMAN]
    outcomes: list[Outcome] = []
    for i in range(num_outcomes):
        artifact = Artifact.propose(
            type="opportunity",
            owner=f"{org_name}-toy",
            payload=f'{{"toy_index": {i}}}',
            rationale=f"toy candidate {i} for demo/testing datahub_emit.py",
        )
        passed = random.random() > 0.3
        gate_result = GateResult(
            gate_name="toy:scaffold_check",
            determinism=random.choice(determinisms),
            passed=passed,
            evidence=f"synthetic evidence for outcome {i}",
        )
        artifact.record_gate(gate_result)
        if passed:
            artifact.accept(because="synthetic gate passed")
        else:
            artifact.reject()
        outcomes.append(
            Outcome(
                artifact=artifact,
                accepted=passed,
                gate_results=[gate_result],
                # Never persisted to a real MemoryStore — this is synthetic
                # demo data — but Outcome.memory_path is typed as Path
                # (other call sites do memory_path.parent.name), so a
                # placeholder keeps that invariant honest for any code that
                # reuses this toy OrgRun beyond datahub_emit itself.
                memory_path=Path("toy") / org_name / f"outcome-{i}.json",
            )
        )
    return OrgRun(
        org=org_name,
        goal="toy demo run for datahub_emit.py",
        accepted=any(o.accepted for o in outcomes),
        outcomes=outcomes,
        informed_by=[],
        run_id=run_id,
        activity=[],
    )


if __name__ == "__main__":
    import sys
    import uuid

    run = build_toy_org_run("hunter-demo", uuid.uuid4().hex[:8])
    urns = emit_org_run(run)
    print(f"emitted {run.org}-{run.run_id}: {len(urns)} outcomes", file=sys.stderr)
    for index, urn in urns.items():
        print(f"  outcome {index}: {urn}", file=sys.stderr)
