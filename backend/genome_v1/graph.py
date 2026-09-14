"""Deterministic, read-only projection of a Genome descriptor into three graphs."""

from __future__ import annotations

import hashlib
from typing import Any

from .canonical import digest_for
from .models import CrossGraphEdge, GenomeDescriptor, GenomeRef, GraphEdge, GraphNode, GraphProjection


def _identifier(prefix: str, value: str) -> str:
    candidate = f"{prefix}-{value}"
    if len(candidate) <= 128:
        return candidate
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]}"


def _projection_payload(value: dict[str, Any]) -> dict[str, Any]:
    value = dict(value)
    value.pop("projection_digest", None)
    return value


def project_graph(descriptor: GenomeDescriptor) -> GraphProjection:
    """Project declared material without manufacturing execution observations."""
    resolved = descriptor.with_digest()
    genome_ref = GenomeRef(genome_id=resolved.genome_id, digest=resolved.content_digest)
    mechanism_nodes: list[GraphNode] = []
    mechanism_edges: list[GraphEdge] = []
    execution_nodes: list[GraphNode] = []
    execution_edges: list[GraphEdge] = []
    evidence_nodes: list[GraphNode] = []
    evidence_edges: list[GraphEdge] = []
    cross_graph_edges: list[CrossGraphEdge] = []

    for component in sorted(resolved.components, key=lambda item: item.component_id):
        mechanism_nodes.append(
            GraphNode(
                node_id=_identifier("m", component.component_id), graph="mechanism", kind=component.kind,
                label=component.name, ref_id=component.component_id, digest=component.config_digest,
                attributes={"lifecycle": component.lifecycle, "version": component.version},
            )
        )
        execution_node = _identifier("x", component.component_id)
        execution_nodes.append(
            GraphNode(
                node_id=execution_node, graph="execution", kind="execution_state",
                label=f"{component.name}: unknown (no bound execution observation)", ref_id=component.component_id,
                attributes={"state": "unknown", "admission": "HOLD", "reason": "no bound execution record"},
            )
        )
        cross_graph_edges.append(
            CrossGraphEdge(
                edge_id=_identifier("mx", component.component_id), subject_graph="mechanism", subject=_identifier("m", component.component_id),
                predicate="configured_as", object_graph="execution", object=execution_node, provenance_refs=("execution-evidence",),
            )
        )
    execution_status = _identifier("x", f"status-{resolved.genome_id}")
    execution_nodes.append(
        GraphNode(
            node_id=execution_status, graph="execution", kind="execution_summary",
            label="execution unknown; descriptor-only projection", attributes={"state": "unknown", "admission": "HOLD"},
        )
    )
    for component in sorted(resolved.components, key=lambda item: item.component_id):
        execution_edges.append(
            GraphEdge(
                edge_id=_identifier("xe", component.component_id), graph="execution",
                subject=_identifier("x", component.component_id), predicate="declared_execution_state", object=execution_status,
            )
        )
    for capability in sorted(resolved.capabilities, key=lambda item: item.capability_id):
        mechanism_nodes.append(
            GraphNode(
                node_id=_identifier("m", capability.capability_id), graph="mechanism", kind="capability",
                label=capability.capability_id, ref_id=capability.capability_id,
                attributes={"domain": capability.domain, "mode": capability.mode}, provenance_refs=capability.evidence_refs,
            )
        )
    for relation in sorted(resolved.relations, key=lambda item: item.relation_id):
        mechanism_edges.append(
            GraphEdge(
                edge_id=_identifier("me", relation.relation_id), graph="mechanism",
                subject=_identifier("m", relation.subject_id), predicate=relation.predicate,
                object=_identifier("m", relation.object_id), provenance_refs=relation.evidence_refs,
            )
        )
    for component in sorted(resolved.components, key=lambda item: item.component_id):
        for capability_id in sorted(component.capability_ids):
            mechanism_edges.append(
                GraphEdge(
                    edge_id=_identifier("mc", f"{component.component_id}-{capability_id}"), graph="mechanism",
                    subject=_identifier("m", component.component_id), predicate="declares_capability",
                    object=_identifier("m", capability_id),
                )
            )

    for source in sorted(resolved.source_bindings, key=lambda item: item.source_id):
        evidence_nodes.append(
            GraphNode(
                node_id=_identifier("e", source.source_id), graph="evidence", kind="source_binding", label=source.uri,
                ref_id=source.source_id, digest=source.content_digest,
                attributes={"provenance": source.provenance, "revision": source.revision, "source_date": None if source.source_date is None else source.source_date.isoformat()},
            )
        )
    authority_id = _identifier("e", f"authority-{resolved.genome_id}")
    evidence_nodes.append(
        GraphNode(
            node_id=authority_id, graph="evidence", kind="authority", label="local descriptor projection only",
            attributes={"status": "declared", "integrity_not_truth": True, "claim_ceiling": "local descriptor projection only"},
        )
    )
    execution_evidence_id = _identifier("e", f"execution-{resolved.genome_id}")
    evaluation_evidence_id = _identifier("e", f"evaluation-{resolved.genome_id}")
    evidence_nodes.extend((
        GraphNode(node_id=execution_evidence_id, graph="evidence", kind="execution_capture_status", label="execution capture unknown", ref_id="execution-evidence", attributes={"state": "unknown", "admission": "HOLD"}),
        GraphNode(node_id=evaluation_evidence_id, graph="evidence", kind="evaluation_status", label="evaluation unknown", ref_id="evaluation-evidence", attributes={"state": "unknown", "admission": "HOLD"}),
    ))
    for component in sorted(resolved.components, key=lambda item: item.component_id):
        cross_graph_edges.append(
            CrossGraphEdge(
                edge_id=_identifier("xe", f"capture-{component.component_id}"), subject_graph="execution", subject=_identifier("x", component.component_id),
                predicate="captured_by", object_graph="evidence", object=execution_evidence_id, provenance_refs=("execution-evidence",),
            )
        )
    cross_graph_edges.append(
        CrossGraphEdge(
            edge_id=_identifier("xe", f"evaluate-{resolved.genome_id}"), subject_graph="execution", subject=execution_status,
            predicate="evaluated_by", object_graph="evidence", object=evaluation_evidence_id, provenance_refs=("evaluation-evidence",),
        )
    )
    for source in sorted(resolved.source_bindings, key=lambda item: item.source_id):
        evidence_edges.append(
            GraphEdge(
                edge_id=_identifier("es", f"{source.source_id}-{resolved.genome_id}"), graph="evidence",
                subject=_identifier("e", source.source_id), predicate="bounds", object=authority_id,
            )
        )
    for protocol in sorted(resolved.protocols, key=lambda item: item.protocol_id):
        source_id = protocol.source.source_id
        if source_id not in {source.source_id for source in resolved.source_bindings}:
            node_id = _identifier("e", source_id)
            evidence_nodes.append(
                GraphNode(node_id=node_id, graph="evidence", kind="protocol_source", label=protocol.source.uri,
                          ref_id=source_id, digest=protocol.source.content_digest,
                          attributes={"provenance": protocol.source.provenance, "revision": protocol.source.revision}))
        evidence_edges.append(
            GraphEdge(edge_id=_identifier("ep", protocol.protocol_id), graph="evidence",
                      subject=_identifier("e", source_id), predicate="supports_descriptor", object=authority_id)
        )

    raw = {
        "genome_ref": genome_ref,
        "mechanism_nodes": tuple(mechanism_nodes), "mechanism_edges": tuple(mechanism_edges),
        "execution_nodes": tuple(execution_nodes), "execution_edges": tuple(execution_edges),
        "evidence_nodes": tuple(evidence_nodes), "evidence_edges": tuple(evidence_edges),
        "cross_graph_edges": tuple(cross_graph_edges),
    }
    return GraphProjection(**raw, projection_digest=digest_for(_projection_payload(raw), domain="scaffold-arena.genome.projection"))
