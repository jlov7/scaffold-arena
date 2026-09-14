"""Strict static input contracts for Harness X-Ray v1.

X-Ray accepts already captured bytes and caller-declared findings only.  It is
not a crawler, parser runner, package inspector, or execution surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canonical import snapshot_digest

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=16_384)]
EVIDENCE_STATES = ("declared", "observed", "inferred", "verified", "unsupported", "unknown")
EvidenceState = Literal["declared", "observed", "inferred", "verified", "unsupported", "unknown"]
XRaySourceKind = Literal["auto", "repository", "acp", "cli", "sdk", "otel_bundle", "recorded_run"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class EvidenceFinding(_Model):
    finding_id: Identifier
    subject: Text
    statement: Text
    evidence_state: EvidenceState
    evidence_refs: tuple[Identifier, ...] = Field(default=(), max_length=64)
    inference_basis: Text | None = None
    verification_method: Text | None = None
    limitation: Text | None = None

    @model_validator(mode="after")
    def _evidence_rules(self) -> EvidenceFinding:
        refs = self.evidence_refs
        if len(refs) != len(set(refs)):
            raise ValueError("evidence_refs must be unique")
        if self.evidence_state == "unknown" and (refs or self.inference_basis or self.verification_method):
            raise ValueError("unknown findings cannot carry evidence or a method")
        if self.evidence_state in {"observed", "unsupported"} and not refs:
            raise ValueError(f"{self.evidence_state} findings require evidence_refs")
        if self.evidence_state == "inferred" and (not refs or not self.inference_basis):
            raise ValueError("inferred findings require evidence_refs and inference_basis")
        if self.evidence_state == "verified" and (not refs or not self.verification_method):
            raise ValueError("verified findings require evidence_refs and verification_method")
        if self.evidence_state == "unsupported" and not self.limitation:
            raise ValueError("unsupported findings require a limitation")
        if self.evidence_state != "inferred" and self.inference_basis is not None:
            raise ValueError("inference_basis is only valid for inferred findings")
        if self.evidence_state != "verified" and self.verification_method is not None:
            raise ValueError("verification_method is only valid for verified findings")
        return self


class XraySourceSnapshot(_Model):
    schema_version: Literal["scaffold-arena.xray/1"] = "scaffold-arena.xray/1"
    snapshot_id: Identifier
    source_name: Text
    source_uri: Text | None = None
    source_revision: Text | None = None
    captured_at: datetime
    source_media_type: Literal["text/plain", "application/json", "text/markdown"]
    source_text: Annotated[str, Field(min_length=1, max_length=1_000_000)]
    source_refs: tuple[Identifier, ...] = Field(default=(), max_length=256)
    findings: tuple[EvidenceFinding, ...] = Field(default=(), max_length=1_024)
    source_digest: Digest | None = None

    @field_validator("captured_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _snapshot_rules(self) -> XraySourceSnapshot:
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("source_refs must be unique")
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding ids must be unique")
        expected = snapshot_digest(self)
        if self.source_digest is not None and self.source_digest != expected:
            raise ValueError("source_digest does not bind canonical source snapshot bytes")
        return self

    def with_digest(self) -> XraySourceSnapshot:
        return self.model_copy(update={"source_digest": snapshot_digest(self)})


class XRayRequest(_Model):
    """A bounded, already-captured artifact to inspect without executing it."""

    source_artifact_digest: Annotated[str, Field(pattern=r"^(?:sha256:)?[a-f0-9]{64}$")]
    source_kind: XRaySourceKind = "auto"
    profile_id: Identifier | None = None


class DetectedMechanism(_Model):
    mechanism_id: Identifier
    status: EvidenceState
    evidence_refs: list[str] = Field(default_factory=list, max_length=64)
    inference_basis: str | None = Field(default=None, max_length=16_384)
    verification_method: str | None = Field(default=None, max_length=16_384)
    limitation: str | None = Field(default=None, max_length=16_384)

    @model_validator(mode="after")
    def _state_rules(self) -> DetectedMechanism:
        if self.status == "unknown" and self.evidence_refs:
            raise ValueError("unknown mechanisms cannot carry evidence refs")
        if self.status == "inferred" and (not self.evidence_refs or not self.inference_basis):
            raise ValueError("inferred mechanisms require evidence refs and an inference basis")
        if self.status == "verified" and (not self.evidence_refs or not self.verification_method):
            raise ValueError("verified mechanisms require evidence refs and a verification method")
        if self.status == "unsupported" and not self.limitation:
            raise ValueError("unsupported mechanisms require a limitation")
        return self


class XRayReport(_Model):
    """A redacted, content-addressed static diagnostic report."""

    report_id: Identifier
    report_digest: str
    analysis_digest: str
    claim_ceiling: str
    report_artifact_digest: str
    candidate_genome: dict[str, object]
    mechanism_graph: dict[str, object]
    detected_mechanisms: list[DetectedMechanism]
    mechanisms: list[DetectedMechanism]
    unobservable_controls: list[str]
    confounds: list[str]
    security_paths: list[str]
    first_study: dict[str, object]
    expected_attempts: int | None
    expected_cost_interval: dict[str, object]
    evidence_ceiling: str
    limitations: list[str]
    provider_execution_started: Literal[False] = False
    execution_started: Literal[False] = False
    network_requested: Literal[False] = False
    idempotent_replay: bool = False
