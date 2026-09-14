"""Strict, inert data contracts for Harness Genome v1.

These records describe declared, observed, and evidence-bound material.  They
do not execute an adapter, fetch a source, or elevate an evidence claim.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlparse

from protocol_v1.models import ExtensibleProtocolModel, ProtocolModel

from .canonical import CANONICALIZATION, genome_digest

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1, max_length=4096)]

GenomeSchema = Literal["scaffold-arena.genome/1"]
GraphName = Literal["mechanism", "execution", "evidence"]


class GenomeModel(ProtocolModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Keep the public wire contract on aliases, including ``schema``."""
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


def _is_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _reject_controls(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field_name} cannot contain control characters")
    return value


class GenomeRef(GenomeModel):
    genome_id: Identifier
    schema_version: GenomeSchema = Field(
        default="scaffold-arena.genome/1", alias="schema", serialization_alias="schema"
    )
    digest: Sha256Digest


class SourceBinding(GenomeModel):
    source_id: Identifier
    uri: NonEmpty
    revision: NonEmpty | None = None
    content_digest: Sha256Digest | None = None
    retrieved_at: datetime
    license_spdx: NonEmpty | None = None
    source_date: date | None = None
    provenance: Literal["official_primary", "local_observation", "user_declared", "fixture"]

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        value = _reject_controls(value, "uri")
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("uri must be a credential-free HTTP(S) provenance URL")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("uri must use HTTPS unless it is literal loopback")
        sensitive = {"access_token", "api_key", "apikey", "auth", "authorization", "cookie", "key", "password", "secret", "token"}
        if any(part.partition("=")[0].casefold() in sensitive for part in parsed.query.split("&") if part):
            raise ValueError("uri query cannot contain credential-bearing parameters")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        return _is_aware(value, "retrieved_at")


class AcpRegistrySnapshot(GenomeModel):
    registry_uri: Literal["https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"]
    registry_schema_version: NonEmpty
    source_revision: NonEmpty | None = None
    content_digest: Sha256Digest
    captured_at: datetime
    agent_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=256)

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        return _is_aware(value, "captured_at")

    @model_validator(mode="after")
    def validate_agent_ids(self) -> AcpRegistrySnapshot:
        if tuple(sorted(self.agent_ids)) != self.agent_ids or len(set(self.agent_ids)) != len(self.agent_ids):
            raise ValueError("agent_ids must be unique and sorted")
        return self


class AcpAgentIdentity(GenomeModel):
    agent_id: Identifier
    display_name: NonEmpty
    version: NonEmpty
    repository_uri: NonEmpty | None = None
    license_spdx: NonEmpty | None = None
    distribution: Literal["binary", "npx", "uvx"]
    distribution_ref: NonEmpty
    distribution_digest: Sha256Digest | None = None
    executable_argv: tuple[NonEmpty, ...] = Field(min_length=1, max_length=32)
    source_snapshot: AcpRegistrySnapshot

    @field_validator("executable_argv")
    @classmethod
    def validate_fixed_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any("\x00" in item or "\n" in item or "\r" in item for item in value):
            raise ValueError("executable_argv entries cannot contain control separators")
        return value

    @model_validator(mode="after")
    def validate_registry_membership(self) -> AcpAgentIdentity:
        if self.agent_id not in self.source_snapshot.agent_ids:
            raise ValueError("agent_id must be present in source_snapshot.agent_ids")
        if self.distribution_ref.lower() in {"latest", "main", "master"}:
            raise ValueError("distribution_ref must be pinned, not mutable")
        return self


class AcpBridgePolicy(GenomeModel):
    protocol_version: Literal["1"] = "1"
    transport: Literal["stdio"] = "stdio"
    filesystem: Literal["deny", "workspace_only"] = "deny"
    terminal: Literal["deny", "isolated_only"] = "deny"
    permission_requests: Literal["deny", "human_pending"] = "deny"
    elicitation: Literal["deny", "human_pending"] = "deny"
    max_wall_time_seconds: int = Field(ge=1, le=86_400)
    max_idle_seconds: int = Field(ge=1, le=86_400)
    max_message_bytes: int = Field(ge=1, le=100_000_000)
    max_event_count: int = Field(ge=1, le=10_000_000)
    max_stdout_bytes: int = Field(ge=0, le=1_000_000_000)
    max_stderr_bytes: int = Field(ge=0, le=1_000_000_000)
    max_artifact_bytes: int = Field(ge=0, le=10_000_000_000)
    max_memory_bytes: int = Field(default=512 * 1024 * 1024, ge=16 * 1024 * 1024, le=128 * 1024 * 1024 * 1024)
    max_processes: int = Field(default=16, ge=1, le=256)
    home_root_digest: Sha256Digest
    xdg_roots_digest: Sha256Digest
    workspace_root_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_bounds(self) -> AcpBridgePolicy:
        if self.max_idle_seconds > self.max_wall_time_seconds:
            raise ValueError("max_idle_seconds cannot exceed max_wall_time_seconds")
        return self


class AcpLaunchAttestation(GenomeModel):
    """Operator-owned authorization for one fixed, contained ACP launch."""

    attestation_id: Identifier
    registry_snapshot_digest: Sha256Digest
    agent_id: Identifier
    distribution_digest: Sha256Digest
    argv_digest: Sha256Digest
    sandbox_launcher_digest: Sha256Digest
    sandbox_launcher_argv: tuple[NonEmpty, ...] = Field(min_length=1, max_length=64)
    enforced_limits_digest: Sha256Digest
    authority_ceiling: Literal["fixture_containment_only"] = "fixture_containment_only"
    integrity_not_truth: Literal[True] = True

    @field_validator("sandbox_launcher_argv")
    @classmethod
    def validate_launcher_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value[0].startswith("/") or any("\x00" in item or "\n" in item or "\r" in item for item in value):
            raise ValueError("sandbox_launcher_argv must be a fixed absolute argv without control separators")
        return value


class CheckResult(GenomeModel):
    check_id: Identifier
    status: Literal["PASS", "HOLD", "FAIL"]
    detail: NonEmpty


class AcpBridgeReceipt(GenomeModel):
    bridge_id: Identifier
    agent_identity: AcpAgentIdentity
    policy_digest: Sha256Digest
    protocol_version: Literal["1"]
    initialize_result_digest: Sha256Digest | None = None
    session_id_digest: Sha256Digest | None = None
    transcript_artifact_digest: Sha256Digest
    cancellation: Literal["not_requested", "acknowledged", "forced", "uncertain"]
    denied_operations: tuple[NonEmpty, ...] = Field(default=(), max_length=256)
    checks: tuple[CheckResult, ...] = Field(min_length=1, max_length=256)
    authority_ceiling: Literal["local_acp_process_observation"] = "local_acp_process_observation"
    integrity_not_truth: Literal[True] = True


class ProtocolBinding(GenomeModel):
    protocol_id: NonEmpty
    version: NonEmpty
    source: SourceBinding
    support_level: Literal[
        "catalog_only", "descriptor_only", "import_only", "fixture_conformance", "observed_adapter", "claim_eligible"
    ]
    unsupported_claims: tuple[NonEmpty, ...] = Field(min_length=1, max_length=128)

    @field_validator("protocol_id")
    @classmethod
    def validate_protocol_id(cls, value: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", value) is None:
            raise ValueError("protocol_id must be a lowercase protocol identifier")
        return value


class Subject(GenomeModel):
    kind: Literal["harness_stack"]
    name: NonEmpty


ComponentKind = Literal[
    "model", "orchestrator", "agent_runtime", "tool_transport", "tool", "memory", "state_store", "checkpoint",
    "approval_policy", "sandbox", "evaluator", "telemetry", "cli", "adapter", "artifact_store", "ui",
]


class Component(GenomeModel):
    component_id: Identifier
    kind: ComponentKind
    name: NonEmpty
    version: NonEmpty | None = None
    source: SourceBinding | None = None
    license_spdx: NonEmpty | None = None
    config_digest: Sha256Digest | None = None
    capability_ids: tuple[Identifier, ...] = Field(default=(), max_length=128)
    lifecycle: Literal["declared", "observed", "verified"]
    mutability: Literal["immutable", "mutable", "unknown"] = "unknown"
    observability_surfaces: tuple[Literal["none", "logs", "metrics", "traces", "events"], ...] = ()
    security_responsibilities: tuple[Literal["none", "access_control", "data_boundary", "execution_boundary", "secret_handling"], ...] = ()
    compatibility_requirements: tuple[NonEmpty, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_capabilities(self) -> Component:
        if len(set(self.capability_ids)) != len(self.capability_ids):
            raise ValueError("component capability_ids must be unique")
        for values, label in ((self.observability_surfaces, "observability_surfaces"), (self.security_responsibilities, "security_responsibilities"), (self.compatibility_requirements, "compatibility_requirements")):
            if len(values) != len(set(values)):
                raise ValueError(f"component {label} must be unique")
        return self


class Relation(GenomeModel):
    relation_id: Identifier
    subject_id: Identifier
    predicate: Literal["contains", "invokes", "delegates_to", "calls", "stores", "emits", "evaluates", "guards", "exports"]
    object_id: Identifier
    evidence_refs: tuple[Identifier, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_relation(self) -> Relation:
        if self.subject_id == self.object_id:
            raise ValueError("relations cannot self-reference")
        return self


class Capability(GenomeModel):
    capability_id: Identifier
    domain: Literal["tools", "state", "checkpoint", "memory", "delegation", "streaming", "usage", "sandboxing", "approval", "telemetry", "cancellation", "cleanup"]
    mode: Literal["declared", "observed", "verified", "unsupported", "unknown"]
    evidence_refs: tuple[Identifier, ...] = Field(default=(), max_length=128)


class Authority(GenomeModel):
    status: Literal["declared", "observed", "fixture_verified", "live_observed", "independently_reproduced"]
    claim_ceiling: NonEmpty
    limitations: tuple[NonEmpty, ...] = Field(min_length=1, max_length=128)
    exclusions: tuple[NonEmpty, ...] = Field(default=(), max_length=128)


class GenomeDescriptor(ExtensibleProtocolModel, GenomeModel):
    """A content-addressed harness-stack declaration, never an execution plan."""

    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, frozen=True,
        validate_by_name=True, validate_by_alias=True, serialize_by_alias=True,
    )

    schema_version: GenomeSchema = Field(
        default="scaffold-arena.genome/1", alias="schema", serialization_alias="schema"
    )
    genome_id: Identifier
    subject: Subject
    components: tuple[Component, ...] = Field(min_length=1, max_length=256)
    relations: tuple[Relation, ...] = Field(default=(), max_length=512)
    capabilities: tuple[Capability, ...] = Field(default=(), max_length=256)
    protocols: tuple[ProtocolBinding, ...] = Field(default=(), max_length=128)
    source_bindings: tuple[SourceBinding, ...] = Field(default=(), max_length=256)
    acp_identity: AcpAgentIdentity | None = None
    acp_policy: AcpBridgePolicy | None = None
    authority: Authority
    canonicalization: Literal[CANONICALIZATION] = CANONICALIZATION
    genome_digest: Sha256Digest | None = None

    @model_validator(mode="after")
    def validate_descriptor(self) -> GenomeDescriptor:
        component_ids = [component.component_id for component in self.components]
        capability_ids = [capability.capability_id for capability in self.capabilities]
        relation_ids = [relation.relation_id for relation in self.relations]
        protocol_ids = [protocol.protocol_id for protocol in self.protocols]
        source_ids = [source.source_id for source in self.source_bindings]
        for values, label in ((component_ids, "component"), (capability_ids, "capability"), (relation_ids, "relation"), (protocol_ids, "protocol"), (source_ids, "source")):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} ids must be unique")
        component_set = set(component_ids)
        if component_set & set(capability_ids):
            raise ValueError("component and capability ids must use distinct namespaces")
        if any(relation.subject_id not in component_set or relation.object_id not in component_set for relation in self.relations):
            raise ValueError("relations must reference declared components")
        if any(capability_id not in set(capability_ids) for component in self.components for capability_id in component.capability_ids):
            raise ValueError("components must reference declared capabilities")
        if (self.acp_identity is None) != (self.acp_policy is None):
            raise ValueError("acp_identity and acp_policy must appear together")
        calculated = genome_digest(self)
        if self.genome_digest is not None and self.genome_digest != calculated:
            raise ValueError("genome_digest does not bind canonical descriptor bytes")
        return self

    @property
    def content_digest(self) -> str:
        return genome_digest(self)

    def with_digest(self) -> GenomeDescriptor:
        return self.model_copy(update={"genome_digest": self.content_digest})


class GraphNode(GenomeModel):
    node_id: Identifier
    graph: GraphName
    kind: NonEmpty
    label: NonEmpty
    ref_id: Identifier | None = None
    digest: Sha256Digest | None = None
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=64)
    provenance_refs: tuple[Identifier, ...] = Field(default=(), max_length=128)


class GraphEdge(GenomeModel):
    edge_id: Identifier
    graph: GraphName
    subject: Identifier
    predicate: NonEmpty
    object: Identifier
    sequence: int | None = Field(default=None, ge=0)
    provenance_refs: tuple[Identifier, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_edge(self) -> GraphEdge:
        if self.subject == self.object:
            raise ValueError("graph edges cannot self-reference")
        return self


class CrossGraphEdge(GenomeModel):
    edge_id: Identifier
    subject_graph: GraphName
    subject: Identifier
    predicate: Literal["configured_as", "applied_control", "captured_by", "evaluated_by"]
    object_graph: GraphName
    object: Identifier
    provenance_refs: tuple[Identifier, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_cross_graph_edge(self) -> CrossGraphEdge:
        legal = {
            ("configured_as", "mechanism", "execution"),
            ("applied_control", "mechanism", "execution"),
            ("captured_by", "execution", "evidence"),
            ("evaluated_by", "execution", "evidence"),
        }
        if self.subject_graph == self.object_graph or (self.predicate, self.subject_graph, self.object_graph) not in legal:
            raise ValueError("cross graph edge has an unadmitted graph/predicate direction")
        return self


class GraphProjection(GenomeModel):
    genome_ref: GenomeRef
    mechanism_nodes: tuple[GraphNode, ...] = Field(default=(), max_length=1024)
    mechanism_edges: tuple[GraphEdge, ...] = Field(default=(), max_length=2048)
    execution_nodes: tuple[GraphNode, ...] = Field(default=(), max_length=1024)
    execution_edges: tuple[GraphEdge, ...] = Field(default=(), max_length=2048)
    evidence_nodes: tuple[GraphNode, ...] = Field(default=(), max_length=1024)
    evidence_edges: tuple[GraphEdge, ...] = Field(default=(), max_length=2048)
    cross_graph_edges: tuple[CrossGraphEdge, ...] = Field(default=(), max_length=4096)
    projection_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_three_graphs(self) -> GraphProjection:
        groups = {
            "mechanism": (self.mechanism_nodes, self.mechanism_edges, {"contains", "invokes", "delegates_to", "calls", "stores", "emits", "evaluates", "guards", "exports", "declares_capability"}),
            "execution": (self.execution_nodes, self.execution_edges, {"declared_execution_state", "observed_execution_state", "applied_control", "cancelled", "holds"}),
            "evidence": (self.evidence_nodes, self.evidence_edges, {"bounds", "supports_descriptor", "observes", "captures", "evaluates"}),
        }
        node_ids: set[str] = set(); edge_ids: set[str] = set()
        for graph, (nodes, edges, predicates) in groups.items():
            local_nodes = {node.node_id for node in nodes}
            if len(local_nodes) != len(nodes) or any(node.graph != graph for node in nodes):
                raise ValueError(f"{graph} graph nodes must be uniquely owned by that graph")
            if node_ids & local_nodes:
                raise ValueError("graph node ids must not cross graph boundaries")
            node_ids.update(local_nodes)
            local_edges = {edge.edge_id for edge in edges}
            if len(local_edges) != len(edges) or edge_ids & local_edges:
                raise ValueError("graph edge ids must be globally unique")
            edge_ids.update(local_edges)
            for edge in edges:
                if edge.graph != graph or edge.subject not in local_nodes or edge.object not in local_nodes:
                    raise ValueError(f"{graph} edges cannot cross graph boundaries")
                if edge.predicate not in predicates:
                    raise ValueError(f"{graph} edge predicate is not admitted")
        cross_ids = {edge.edge_id for edge in self.cross_graph_edges}
        if len(cross_ids) != len(self.cross_graph_edges) or edge_ids & cross_ids:
            raise ValueError("cross graph edge ids must be globally unique")
        graph_nodes = {graph: {node.node_id for node in nodes} for graph, (nodes, _edges, _predicates) in groups.items()}
        for edge in self.cross_graph_edges:
            if edge.subject not in graph_nodes[edge.subject_graph] or edge.object not in graph_nodes[edge.object_graph]:
                raise ValueError("cross graph edges must resolve to nodes in their declared graphs")
            evidence_refs = {node.ref_id for node in self.evidence_nodes if node.ref_id is not None}
            if not edge.provenance_refs or not set(edge.provenance_refs) <= evidence_refs:
                raise ValueError("cross graph edges require resolvable evidence provenance refs")
        return self


class GenomeCertificationReceipt(GenomeModel):
    receipt_id: Identifier
    genome_digest: Sha256Digest
    checker_id: Identifier
    checker_digest: Sha256Digest
    checks: tuple[CheckResult, ...] = Field(min_length=1, max_length=256)
    verdict: Literal["PASS", "HOLD", "FAIL"]
    authority_ceiling: Literal["local_descriptor_fixture_only"] = "local_descriptor_fixture_only"
    limitations: tuple[NonEmpty, ...] = Field(min_length=1, max_length=128)
    receipt_digest: Sha256Digest
    integrity_not_truth: Literal[True] = True
