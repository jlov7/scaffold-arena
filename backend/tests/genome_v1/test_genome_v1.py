from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from genome_v1 import (
    AcpAgentIdentity,
    AcpBridgePolicy,
    AcpRegistrySnapshot,
    Authority,
    Capability,
    Component,
    GenomeDescriptor,
    GraphEdge,
    GraphNode,
    GraphProjection,
    ProtocolBinding,
    Relation,
    SourceBinding,
    Subject,
    canonical_genome_bytes,
    certify_descriptor,
    check_intervention_locality,
    genome_digest,
    load_standards_catalog,
    project_graph,
    semantic_diff,
)


NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def source(source_id: str = "source-core") -> SourceBinding:
    return SourceBinding(
        source_id=source_id, uri="https://example.invalid/source", revision="v1", content_digest=HASH_A,
        retrieved_at=NOW, license_spdx="MIT", source_date=date(2026, 8, 18), provenance="fixture",
    )


def descriptor(**updates: object) -> GenomeDescriptor:
    values: dict[str, object] = {
        "genome_id": "genome-core", "subject": Subject(kind="harness_stack", name="Caf\u00e9 harness"),
        "components": (Component(component_id="model-core", kind="model", name="Fixture model", version="1", source=source(), config_digest=HASH_A, capability_ids=("tools-core",), lifecycle="declared"),),
        "relations": (),
        "capabilities": (Capability(capability_id="tools-core", domain="tools", mode="declared"),),
        "protocols": (ProtocolBinding(protocol_id="acp", version="1", source=source("source-acp"), support_level="fixture_conformance", unsupported_claims=("No safety claim.",)),),
        "source_bindings": (source(),),
        "authority": Authority(status="declared", claim_ceiling="descriptor only", limitations=("No runtime observation.",)),
    }
    values.update(updates)
    return GenomeDescriptor(**values)


def test_descriptor_is_strict_domain_separated_and_binds_its_digest():
    first = descriptor()
    bound = first.with_digest()
    assert bound.genome_digest == genome_digest(first)
    assert canonical_genome_bytes(first) != canonical_genome_bytes(bound)
    assert genome_digest(first).startswith("sha256:")
    assert genome_digest(first) == genome_digest(first.model_copy(update={"subject": Subject(kind="harness_stack", name="Cafe\u0301 harness")}))
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GenomeDescriptor.model_validate({**first.model_dump(), "unknown": True})
    with pytest.raises(ValidationError, match="genome_digest does not bind"):
        first.model_copy(update={"genome_digest": HASH_B}).__class__(**{**first.model_dump(), "genome_digest": HASH_B})


def test_acp_identity_requires_captured_registry_membership_and_pinned_ref():
    snapshot = AcpRegistrySnapshot(
        registry_uri="https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json",
        registry_schema_version="1.0.0", content_digest=HASH_A, captured_at=NOW, agent_ids=("codex-acp",),
    )
    identity = AcpAgentIdentity(agent_id="codex-acp", display_name="Codex", version="1", distribution="npx", distribution_ref="@openai/codex@0.139.0", executable_argv=("codex-acp",), source_snapshot=snapshot)
    assert identity.agent_id == "codex-acp"
    with pytest.raises(ValidationError, match="pinned"):
        identity.model_copy(update={"distribution_ref": "latest"}).__class__(**{**identity.model_dump(), "distribution_ref": "latest"})
    with pytest.raises(ValidationError, match="max_idle"):
        AcpBridgePolicy(max_wall_time_seconds=10, max_idle_seconds=11, max_message_bytes=1, max_event_count=1, max_stdout_bytes=0, max_stderr_bytes=0, max_artifact_bytes=0, home_root_digest=HASH_A, xdg_roots_digest=HASH_B, workspace_root_digest=HASH_C)


def test_graph_projection_is_deterministic_three_envelope_with_explicit_unknown_execution_state():
    first = project_graph(descriptor())
    second = project_graph(descriptor())
    assert first.projection_digest == second.projection_digest
    assert {node.graph for node in first.mechanism_nodes} == {"mechanism"}
    assert {node.graph for node in first.execution_nodes} == {"execution"}
    assert all(node.attributes.get("state") == "unknown" for node in first.execution_nodes)
    assert all(edge.predicate == "declared_execution_state" for edge in first.execution_edges)
    assert {edge.predicate for edge in first.cross_graph_edges} >= {"configured_as", "captured_by", "evaluated_by"}
    assert {node.graph for node in first.evidence_nodes} == {"evidence"}
    assert first.genome_ref.digest == descriptor().content_digest


def test_semantic_diff_uses_stable_component_ids_and_locality_fails_closed():
    before = descriptor()
    after = descriptor(components=(Component(component_id="model-core", kind="model", name="Fixture model", version="1", source=source(), config_digest=HASH_B, capability_ids=("tools-core",), lifecycle="declared"),))
    diff = semantic_diff(before, after)
    assert [change.path for change in diff.changed] == ["/components/model-core/config_digest"]
    assert diff.classifications == ("configuration",)
    local = check_intervention_locality(before, after, target_path="/components/model-core/config_digest", operation="set")
    assert local.code == "HOLD_APPLIED_CONTROL_RECEIPT_REQUIRED"
    nonlocal_result = check_intervention_locality(before, descriptor(capabilities=(Capability(capability_id="tools-core", domain="tools", mode="observed"),)), target_path="/components/model-core/config_digest", operation="set")
    assert nonlocal_result.code == "HOLD_INTERVENTION_NONLOCAL"
    caller_allowlisted = check_intervention_locality(before, descriptor(capabilities=(Capability(capability_id="tools-core", domain="tools", mode="observed"),)), target_path="/components/model-core/config_digest", operation="set", mutation_closure=("/capabilities",))
    assert caller_allowlisted.code == "HOLD_INTERVENTION_NONLOCAL"


def test_nested_set_members_are_canonical_and_do_not_create_diff_noise():
    before = descriptor()
    reordered = descriptor(components=(Component(component_id="model-core", kind="model", name="Fixture model", version="1", source=source(), config_digest=HASH_A, capability_ids=("state-core", "tools-core"), lifecycle="declared"),), capabilities=(Capability(capability_id="tools-core", domain="tools", mode="declared"), Capability(capability_id="state-core", domain="state", mode="declared")))
    reordered_again = reordered.model_copy(update={"components": (reordered.components[0].model_copy(update={"capability_ids": ("tools-core", "state-core")}),)})
    assert reordered.content_digest == reordered_again.content_digest
    assert semantic_diff(reordered, reordered_again).changed == ()


def test_component_contract_sets_are_unique_and_canonical() -> None:
    component = Component(component_id="model-core", kind="model", name="Fixture model", version="1", source=source(), config_digest=HASH_A, capability_ids=("tools-core",), lifecycle="declared", observability_surfaces=("traces", "logs"), security_responsibilities=("secret_handling", "access_control"), compatibility_requirements=("api-v1", "python-3"))
    reversed_component = component.model_copy(update={"observability_surfaces": ("logs", "traces"), "security_responsibilities": ("access_control", "secret_handling"), "compatibility_requirements": ("python-3", "api-v1")})
    first, second = descriptor(components=(component,)), descriptor(components=(reversed_component,))
    assert first.content_digest == second.content_digest
    assert semantic_diff(first, second).changed == ()
    with pytest.raises(ValidationError, match="observability_surfaces"):
        Component(component_id="duplicate-core", kind="model", name="x", lifecycle="declared", observability_surfaces=("logs", "logs"))


def test_graph_projection_rejects_cross_graph_edges_and_illegal_predicates():
    ref = descriptor().with_digest()
    raw = {
        "genome_ref": {"genome_id": ref.genome_id, "digest": ref.content_digest},
        "mechanism_nodes": (GraphNode(node_id="m-a", graph="mechanism", kind="component", label="a"), GraphNode(node_id="m-b", graph="mechanism", kind="component", label="b")),
        "mechanism_edges": (GraphEdge(edge_id="edge-a", graph="mechanism", subject="m-a", predicate="bounds", object="m-b"),),
        "execution_nodes": (), "execution_edges": (), "evidence_nodes": (), "evidence_edges": (),
        "projection_digest": HASH_A,
    }
    with pytest.raises(ValidationError):
        GraphProjection(**raw)


def test_catalog_is_static_official_data_and_certification_stays_local_only():
    catalog = load_standards_catalog()
    assert {entry.standard_id for entry in catalog} >= {"agent-client-protocol", "mcp", "a2a", "codex-cli"}
    assert all(entry.source_date == date(2026, 8, 18) for entry in catalog)
    receipt = certify_descriptor(descriptor())
    assert receipt.verdict == "PASS"
    assert receipt.authority_ceiling == "local_descriptor_fixture_only"
    assert receipt.integrity_not_truth is True
