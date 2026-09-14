"""Strict, inert contracts for the Harness Mechanism Atlas v1.

The Atlas is curated provenance and semantic metadata.  It neither imports nor
executes a harness and must not be read as interoperability evidence.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field, model_validator

from .canonical import CANONICALIZATION, bytes_digest, digest_for
from .models import GenomeModel, NonEmpty, Sha256Digest

AtlasId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")]
MechanismId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")]
RelativePath = Annotated[str, Field(min_length=1, max_length=512)]
HttpsUrl = Annotated[str, Field(pattern=r"^https://[^\s?#]+(?:[?#][^\s]*)?$")]

ATLAS_SCHEMA = "scaffold-arena.harness-mechanism-atlas/1"
CITATION_SCHEMA = "scaffold-arena.harness-mechanism-atlas-citations/1"
RELEASE_DIGEST_SCHEMA = "scaffold-arena.harness-mechanism-atlas-release-digest/1"
ATLAS_DOMAIN = "scaffold-arena.harness-mechanism-atlas"
CITATION_DOMAIN = "scaffold-arena.harness-mechanism-atlas-citations"
RELEASE_DOMAIN = "scaffold-arena.harness-mechanism-atlas-release-digest"


def _unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


def _safe_relative_path(value: str, label: str = "path") -> str:
    if value.startswith("/") or "\\" in value or "//" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{label} must be a safe repository-relative path")
    return value


class NativeScaffoldProfile(GenomeModel):
    profile_kind: Literal["native_scaffold"] = "native_scaffold"
    phase_sequence: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)
    provider_call_shape: NonEmpty
    local_validation_repair: NonEmpty
    configuration_knobs: tuple[NonEmpty, ...] = Field(min_length=1, max_length=32)


class GraphOrchestratorProfile(GenomeModel):
    profile_kind: Literal["graph_orchestrator"] = "graph_orchestrator"
    state_graph_model: NonEmpty
    node_edge_model: NonEmpty
    checkpoint_scope: NonEmpty
    store_scope: NonEmpty
    interrupt_resume_semantics: NonEmpty


class SdkRuntimeProfile(GenomeModel):
    profile_kind: Literal["sdk_runtime"] = "sdk_runtime"
    agent_loop: NonEmpty
    handoff_ownership: NonEmpty
    guardrail_phase_tripwire: NonEmpty
    session_tracing_surfaces: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)


class CodingCliProfile(GenomeModel):
    profile_kind: Literal["coding_cli"] = "coding_cli"
    cli_session: NonEmpty
    approval_permission_mode: NonEmpty
    tool_filesystem_terminal_surface: NonEmpty
    containment_invariant: NonEmpty


class ToolProtocolProfile(GenomeModel):
    profile_kind: Literal["tool_protocol"] = "tool_protocol"
    prompts_primitive: NonEmpty
    resources_primitive: NonEmpty
    tools_primitive: NonEmpty
    control_owner: NonEmpty
    schemas: NonEmpty
    cancellation_task_support: NonEmpty
    authorization_consent: NonEmpty


class AgentProtocolProfile(GenomeModel):
    profile_kind: Literal["agent_protocol"] = "agent_protocol"
    lifecycle_objects: tuple[NonEmpty, ...] = Field(min_length=2, max_length=16)
    streaming_semantics: NonEmpty
    cancellation_semantics: NonEmpty
    permission_semantics: NonEmpty
    protocol_distinction: NonEmpty


class TelemetrySurfaceProfile(GenomeModel):
    profile_kind: Literal["telemetry_surface"] = "telemetry_surface"
    signal: NonEmpty
    semantic_convention_namespace: NonEmpty
    schema_url: NonEmpty
    span_linkage: NonEmpty


SemanticProfile = Annotated[
    Union[
        NativeScaffoldProfile,
        GraphOrchestratorProfile,
        SdkRuntimeProfile,
        CodingCliProfile,
        ToolProtocolProfile,
        AgentProtocolProfile,
        TelemetrySurfaceProfile,
    ],
    Field(discriminator="profile_kind"),
]


class AtlasFamily(GenomeModel):
    family_id: Literal[
        "native_scaffold", "graph_orchestrator", "sdk_runtime", "coding_cli",
        "tool_protocol", "agent_protocol", "telemetry_surface",
    ]
    display_name: NonEmpty
    semantic_namespace: NonEmpty
    semantic_contract: SemanticProfile
    mechanism_ids: tuple[MechanismId, ...] = Field(min_length=1, max_length=32)
    citation_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=32)
    known_unknown_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_profile(self) -> "AtlasFamily":
        _unique(self.mechanism_ids, "mechanism_ids")
        _unique(self.citation_ids, "citation_ids")
        _unique(self.known_unknown_ids, "known_unknown_ids")
        if self.semantic_contract.profile_kind != self.family_id:
            raise ValueError("semantic_contract profile_kind must match family_id")
        return self


class MechanismIdentity(GenomeModel):
    arena_name: NonEmpty
    identity_kind: Literal["native_source", "external_catalog"]
    catalog_standard_id: AtlasId | None = None
    version: NonEmpty | None = None
    source_revision_state: Literal["pinned", "not_discoverable", "not_captured"]
    license_spdx: NonEmpty | None = None
    citation_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_identity(self) -> "MechanismIdentity":
        _unique(self.citation_ids, "citation_ids")
        if self.identity_kind == "external_catalog" and self.catalog_standard_id is None:
            raise ValueError("external_catalog identity requires catalog_standard_id")
        if self.identity_kind == "native_source" and self.catalog_standard_id is not None:
            raise ValueError("native_source identity cannot claim catalog_standard_id")
        return self


class MechanismDeclaration(GenomeModel):
    mechanism_id: MechanismId
    family_id: AtlasFamily.__annotations__["family_id"]
    identity: MechanismIdentity
    declaration_status: Literal["declared"] = "declared"
    implementation_identity: NonEmpty
    configuration_status: Literal["captured", "not_captured"]
    configuration_digest: Sha256Digest | None = None
    mutability: Literal["immutable", "mutable", "unknown"]
    observability_surfaces: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)
    security_responsibilities: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)
    compatibility_requirements: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)
    evidence_maturity: Literal["source_metadata", "descriptor", "synthetic_fixture", "local_observation", "live_observation", "independent_reproduction"]
    citation_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=16)
    evidence_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=16)
    known_unknown_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_configuration(self) -> "MechanismDeclaration":
        for values, label in ((self.citation_ids, "citation_ids"), (self.evidence_ids, "evidence_ids"), (self.known_unknown_ids, "known_unknown_ids")):
            _unique(values, label)
        if self.configuration_status == "not_captured" and self.configuration_digest is not None:
            raise ValueError("not_captured configuration must have null configuration_digest")
        if self.configuration_status == "captured" and self.configuration_digest is None:
            raise ValueError("captured configuration requires configuration_digest")
        return self


class MechanismObservation(GenomeModel):
    activation_id: AtlasId
    mechanism_id: MechanismId
    status: Literal["not_observed", "synthetic_metadata_fixture", "local_observed", "live_observed", "independently_reproduced"]
    artifact_path: RelativePath | None = None
    artifact_digest: Sha256Digest | None = None
    metadata_shape_only: bool
    evidence_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=16)
    known_unknown_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=32)
    observed_at: str | None = None
    claim_ceiling: NonEmpty
    integrity_not_truth: Literal[True] = True

    @model_validator(mode="after")
    def validate_observation(self) -> "MechanismObservation":
        if self.artifact_path is not None:
            _safe_relative_path(self.artifact_path, "artifact_path")
        _unique(self.evidence_ids, "evidence_ids")
        _unique(self.known_unknown_ids, "known_unknown_ids")
        if self.status == "not_observed" and any((self.artifact_path, self.artifact_digest, self.observed_at)):
            raise ValueError("not_observed cannot carry an activation artifact or timestamp")
        if self.status == "synthetic_metadata_fixture":
            if not self.artifact_path or not self.artifact_digest or not self.metadata_shape_only:
                raise ValueError("synthetic fixture observations require fixture path, digest, and shape-only flag")
        return self



class AtlasEvidence(GenomeModel):
    evidence_id: AtlasId
    kind: Literal["official_source_metadata", "local_source_snapshot", "descriptor_contract", "synthetic_fixture_metadata"]
    maturity: Literal["source_metadata", "descriptor", "synthetic_fixture", "local_observation", "live_observation", "independent_reproduction"]
    authority_ceiling: NonEmpty
    citation_ids: tuple[AtlasId, ...] = Field(default=(), max_length=16)
    artifact_path: RelativePath | None = None
    artifact_digest: Sha256Digest | None = None
    claim_ceiling: NonEmpty
    limitations: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)
    known_unknown_ids: tuple[AtlasId, ...] = Field(min_length=1, max_length=32)
    integrity_not_truth: Literal[True] = True

    @model_validator(mode="after")
    def validate_evidence(self) -> "AtlasEvidence":
        _unique(self.citation_ids, "citation_ids")
        _unique(self.known_unknown_ids, "known_unknown_ids")
        if self.artifact_path is not None:
            _safe_relative_path(self.artifact_path, "artifact_path")
        if not self.citation_ids and self.artifact_path is None:
            raise ValueError("evidence requires a citation or artifact")
        if (self.artifact_path is None) != (self.artifact_digest is None):
            raise ValueError("artifact path and digest must be paired")
        return self


class AtlasKnownUnknown(GenomeModel):
    unknown_id: AtlasId
    subject_kind: Literal["atlas", "family", "mechanism", "citation", "evidence", "observation"]
    subject_id: str
    statement: NonEmpty
    blocked_claims: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)
    resolution_predicate: NonEmpty
    related_citation_ids: tuple[AtlasId, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_unknown(self) -> "AtlasKnownUnknown":
        _unique(self.blocked_claims, "blocked_claims")
        _unique(self.related_citation_ids, "related_citation_ids")
        return self


class AtlasCitation(GenomeModel):
    citation_id: AtlasId
    source_kind: Literal["official_spec", "official_docs", "official_repository", "local_repository_source"]
    url: HttpsUrl
    source_date: str
    revision_discoverability: Literal["pinned", "not_discoverable", "not_captured"]
    source_revision: NonEmpty | None = None
    content_digest: Sha256Digest | None = None
    license_spdx: NonEmpty | None = None
    source_path: RelativePath | None = None
    supported_mechanism_ids: tuple[MechanismId, ...] = Field(default=(), max_length=32)
    supported_family_ids: tuple[AtlasFamily.__annotations__["family_id"], ...] = Field(default=(), max_length=8)
    limitations: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_citation(self) -> "AtlasCitation":
        _unique(self.supported_mechanism_ids, "supported_mechanism_ids")
        _unique(self.supported_family_ids, "supported_family_ids")
        if self.source_path is not None:
            _safe_relative_path(self.source_path, "source_path")
        if self.source_kind == "local_repository_source":
            if not self.source_path or not self.source_revision or not self.content_digest or self.revision_discoverability != "pinned":
                raise ValueError("local sources require path, revision, digest, and pinned revision")
        elif self.source_path is not None:
            raise ValueError("external sources cannot carry local source_path")
        return self


class AtlasCitationManifest(GenomeModel):
    manifest_schema: Literal["scaffold-arena.harness-mechanism-atlas-citations/1"] = CITATION_SCHEMA
    manifest_id: Literal["harness-mechanism-atlas-citations-v1"] = "harness-mechanism-atlas-citations-v1"
    source_date: str
    canonicalization: Literal["arena-json-v1"] = CANONICALIZATION
    citations: tuple[AtlasCitation, ...] = Field(min_length=1, max_length=128)
    manifest_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_citations(self) -> "AtlasCitationManifest":
        _unique(tuple(item.citation_id for item in self.citations), "citation IDs")
        return self


class CatalogReference(GenomeModel):
    path: Literal["backend/genome_v1/data/standards_catalog_v1.json"]
    sha256: Sha256Digest
    source_date: str


class HarnessMechanismAtlas(GenomeModel):
    atlas_schema: Literal["scaffold-arena.harness-mechanism-atlas/1"] = ATLAS_SCHEMA
    atlas_id: Literal["harness-mechanism-atlas-v1"] = "harness-mechanism-atlas-v1"
    source_date: str
    canonicalization: Literal["arena-json-v1"] = CANONICALIZATION
    catalog_ref: CatalogReference
    citation_manifest_path: Literal["backend/genome_v1/data/harness_mechanism_atlas_citations_v1.json"]
    families: tuple[AtlasFamily, ...] = Field(min_length=7, max_length=7)
    declarations: tuple[MechanismDeclaration, ...] = Field(min_length=1, max_length=128)
    observations: tuple[MechanismObservation, ...] = Field(min_length=1, max_length=128)
    evidence: tuple[AtlasEvidence, ...] = Field(min_length=1, max_length=256)
    known_unknowns: tuple[AtlasKnownUnknown, ...] = Field(min_length=1, max_length=256)
    claim_ceiling: NonEmpty
    atlas_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "HarnessMechanismAtlas":
        for values, label in (
            (tuple(item.family_id for item in self.families), "family IDs"),
            (tuple(item.mechanism_id for item in self.declarations), "mechanism IDs"),
            (tuple(item.activation_id for item in self.observations), "activation IDs"),
            (tuple(item.evidence_id for item in self.evidence), "evidence IDs"),
            (tuple(item.unknown_id for item in self.known_unknowns), "unknown IDs"),
        ):
            _unique(values, label)
        return self


class AtlasReleaseEntry(GenomeModel):
    path: RelativePath
    sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_path(self) -> "AtlasReleaseEntry":
        _safe_relative_path(self.path)
        return self


class AtlasReleaseDigest(GenomeModel):
    release_digest_schema: Literal["scaffold-arena.harness-mechanism-atlas-release-digest/1"] = RELEASE_DIGEST_SCHEMA
    atlas_id: Literal["harness-mechanism-atlas-v1"] = "harness-mechanism-atlas-v1"
    source_date: str
    canonicalization: Literal["arena-json-v1"] = CANONICALIZATION
    entries: tuple[AtlasReleaseEntry, ...] = Field(min_length=1, max_length=64)
    release_digest: Sha256Digest

    @model_validator(mode="after")
    def validate_entries(self) -> "AtlasReleaseDigest":
        _unique(tuple(entry.path for entry in self.entries), "release digest paths")
        return self


_SET_ARRAY_IDS = {
    "families": "family_id", "declarations": "mechanism_id", "observations": "activation_id",
    "evidence": "evidence_id", "known_unknowns": "unknown_id", "citations": "citation_id", "entries": "path",
}
_SET_ARRAYS = frozenset({"citation_ids", "mechanism_ids", "known_unknown_ids", "evidence_ids", "related_citation_ids", "supported_mechanism_ids", "supported_family_ids", "observability_surfaces", "security_responsibilities", "compatibility_requirements"})


def _sorted_atlas(value: Any, *, field: str | None = None) -> Any:
    if isinstance(value, dict):
        return {key: _sorted_atlas(item, field=key) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        items = [_sorted_atlas(item) for item in value]
        id_key = _SET_ARRAY_IDS.get(field or "")
        if id_key:
            return sorted(items, key=lambda item: item[id_key])
        if field in _SET_ARRAYS:
            return sorted(items)
        return items
    return value


def atlas_payload(value: HarnessMechanismAtlas | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="json") if isinstance(value, HarnessMechanismAtlas) else dict(value)
    raw.pop("atlas_digest", None)
    return _sorted_atlas(raw)


def citation_payload(value: AtlasCitationManifest | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="json") if isinstance(value, AtlasCitationManifest) else dict(value)
    raw.pop("manifest_digest", None)
    return _sorted_atlas(raw)


def release_digest_payload(value: AtlasReleaseDigest | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="json") if isinstance(value, AtlasReleaseDigest) else dict(value)
    raw.pop("release_digest", None)
    return _sorted_atlas(raw)


def atlas_digest(value: HarnessMechanismAtlas | dict[str, Any]) -> str:
    return digest_for(atlas_payload(value), domain=ATLAS_DOMAIN)


def citation_digest(value: AtlasCitationManifest | dict[str, Any]) -> str:
    return digest_for(citation_payload(value), domain=CITATION_DOMAIN)


def release_digest(value: AtlasReleaseDigest | dict[str, Any]) -> str:
    return digest_for(release_digest_payload(value), domain=RELEASE_DOMAIN)


def file_digest(path: Any) -> str:
    return bytes_digest(path.read_bytes())
