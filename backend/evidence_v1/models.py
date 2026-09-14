"""Content-addressed evidence contracts; integrity is never a truth claim."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from protocol_v1.canonical import canonical_json

Digest = str


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _hash_field() -> Field:
    return Field(pattern=r"^[a-f0-9]{64}$")


class EvidenceClass(StrEnum):
    FIXTURE = "fixture"
    LOCAL_LIVE = "local_live"
    REPLICATED = "replicated"
    CROSS_MODEL = "cross_model"
    HUMAN_CALIBRATED = "human_calibrated"
    INDEPENDENTLY_REPRODUCED = "independently_reproduced"


class ClaimMaturity(StrEnum):
    FIXTURE = "FIXTURE"
    LOCAL_LIVE = "LOCAL_LIVE"
    REPLICATED = "REPLICATED"
    CROSS_MODEL = "CROSS_MODEL"
    HUMAN_CALIBRATED = "HUMAN_CALIBRATED"
    INDEPENDENTLY_REPRODUCED = "INDEPENDENTLY_REPRODUCED"


class EvidenceManifest(EvidenceModel):
    experiment_id: str = Field(min_length=1)
    experiment_hash: Digest = _hash_field()
    study_pack_hash: Digest = _hash_field()
    spec_hash: Digest = _hash_field()
    code_hash: Digest = _hash_field()
    runtime_hash: Digest = _hash_field()
    adapter_hash: Digest = _hash_field()
    model_hash: Digest = _hash_field()
    price_hash: Digest = _hash_field()
    evaluator_hashes: tuple[Digest, ...]
    artifact_hashes: tuple[Digest, ...]
    exclusions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_class: EvidenceClass
    claim_ceiling: str = Field(min_length=1)
    integrity_not_truth: Literal[True] = True

    @model_validator(mode="after")
    def validate_hashes(self) -> EvidenceManifest:
        if not self.evaluator_hashes or not self.artifact_hashes:
            raise ValueError("manifest requires evaluator and artifact hashes")
        for digest in (*self.evaluator_hashes, *self.artifact_hashes):
            if len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ValueError("all manifest hashes must be lowercase SHA-256")
        return self


class EvidenceReceipt(EvidenceModel):
    receipt_id: str = Field(min_length=1)
    manifest_hash: Digest = _hash_field()
    artifact_hashes: tuple[Digest, ...]
    receipt_hash: Digest = _hash_field()
    integrity_not_truth: Literal[True] = True


class ReproductionReceipt(EvidenceModel):
    receipt_id: str = Field(min_length=1)
    original_operator_id: str = Field(min_length=1)
    original_authority_id: str = Field(min_length=1)
    reproducer_operator_id: str = Field(min_length=1)
    reproducer_authority_id: str = Field(min_length=1)
    original_environment_hash: Digest = _hash_field()
    reproducer_environment_hash: Digest = _hash_field()
    original_manifest_hash: Digest = _hash_field()
    reproduced_manifest_hash: Digest = _hash_field()
    deviations: tuple[str, ...] = ()
    # Identity strings are custody metadata, not proof of independent authority.
    independent: Literal[False] = False
    integrity_not_truth: Literal[True] = True

    @model_validator(mode="after")
    def cannot_self_promote(self) -> ReproductionReceipt:
        if self.independent and (
            self.original_operator_id == self.reproducer_operator_id
            or self.original_authority_id == self.reproducer_authority_id
        ):
            raise ValueError(
                "a reproduction cannot be independent when operator or authority matches"
            )
        return self


class EvidenceAdmissionRequest(EvidenceModel):
    """Public request contract for custody-only evidence admission."""

    manifest: EvidenceManifest
    receipt: EvidenceReceipt
    evidence_type: Literal[
        "fixture",
        "local_live",
        "reproduction",
        "cross_model",
        "human_calibration",
        "independent_reproduction",
    ]
    execution_id: str | None

    @field_validator("manifest", mode="before")
    @classmethod
    def validate_manifest_json(cls, value: object) -> EvidenceManifest:
        if isinstance(value, EvidenceManifest):
            return value
        return EvidenceManifest.model_validate_json(canonical_json(value))

    @field_validator("receipt", mode="before")
    @classmethod
    def validate_receipt_json(cls, value: object) -> EvidenceReceipt:
        if isinstance(value, EvidenceReceipt):
            return value
        return EvidenceReceipt.model_validate_json(canonical_json(value))


class RedactedArtifactDescriptor(EvidenceModel):
    original_hash: Digest = _hash_field()
    disposition: Literal["withheld", "redacted"]
    reason: str = Field(min_length=1)


class RedactedExportManifest(EvidenceModel):
    manifest_hash: Digest = _hash_field()
    evidence_class: EvidenceClass
    claim_ceiling: str
    evaluator_hashes: tuple[Digest, ...]
    artifacts: tuple[RedactedArtifactDescriptor, ...]
    integrity_not_truth: Literal[True] = True


class ClaimPromotion(EvidenceModel):
    current: ClaimMaturity
    requested: ClaimMaturity
    promoted: bool
    claim_ceiling: str
    blockers: tuple[str, ...] = ()


class EvidenceVerification(EvidenceModel):
    """A verifier-produced integrity status bound to a concrete receipt and manifest."""

    evidence_type: Literal[
        "fixture",
        "local_live",
        "reproduction",
        "cross_model",
        "human_calibration",
        "independent_reproduction",
    ]
    receipt_id: str = Field(min_length=1)
    receipt_hash: Digest = _hash_field()
    manifest_hash: Digest = _hash_field()
    verifier_id: str = Field(min_length=1)
    verifier_digest: Digest = _hash_field()
    verified: bool
    errors: tuple[str, ...] = ()
    integrity_not_truth: Literal[True] = True

    @model_validator(mode="after")
    def complete_verification(self) -> EvidenceVerification:
        if self.verified and self.errors:
            raise ValueError("verified evidence cannot carry verification errors")
        return self


class ExternalIndependenceAttestation(EvidenceModel):
    """External attestation reference; this code records it but cannot verify real-world identity."""

    reproduction_receipt_hash: Digest = _hash_field()
    original_operator_id: str = Field(min_length=1)
    original_authority_id: str = Field(min_length=1)
    reproducer_operator_id: str = Field(min_length=1)
    reproducer_authority_id: str = Field(min_length=1)
    attester_authority_id: str = Field(min_length=1)
    attestation_evidence_ref: str = Field(min_length=1)
    externally_attested: Literal[True] = True

    @model_validator(mode="after")
    def distinct_custody_identities(self) -> ExternalIndependenceAttestation:
        if (
            self.original_operator_id == self.reproducer_operator_id
            or self.original_authority_id == self.reproducer_authority_id
            or self.attester_authority_id
            in {self.original_authority_id, self.reproducer_authority_id}
        ):
            raise ValueError(
                "external attestation requires an authority distinct from original and reproducer authorities"
            )
        return self


class ReproductionRequest(EvidenceModel):
    """Public request contract for a reproduction custody record."""

    receipt: ReproductionReceipt
    original_evidence_receipt_id: str = Field(min_length=1)
    reproduced_evidence_receipt_id: str = Field(min_length=1)
    external_attestation: ExternalIndependenceAttestation | None

    @field_validator("receipt", mode="before")
    @classmethod
    def validate_receipt_json(cls, value: object) -> ReproductionReceipt:
        if isinstance(value, ReproductionReceipt):
            return value
        return ReproductionReceipt.model_validate_json(canonical_json(value))

    @field_validator("external_attestation", mode="before")
    @classmethod
    def validate_attestation_json(cls, value: object) -> ExternalIndependenceAttestation | None:
        if value is None or isinstance(value, ExternalIndependenceAttestation):
            return value
        return ExternalIndependenceAttestation.model_validate_json(canonical_json(value))


class DerivedEvidenceRequest(EvidenceModel):
    """Public request contract for evidence derived from a durable execution."""

    execution_id: str = Field(min_length=1)
    request_key: str = Field(min_length=1)


class DecisionBrief(EvidenceModel):
    brief_id: str = Field(min_length=1)
    verdict: Literal["ADVANCE", "HOLD", "REJECT"]
    severe_failures: tuple[str, ...]
    outcome_vector: dict[str, object]
    uncertainty: tuple[str, ...]
    exclusions: tuple[str, ...]
    supported_claim_ceiling: str
    blockers: tuple[str, ...]
    next_lawful_action: str = Field(min_length=1)
