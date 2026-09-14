"""Fidelity labels used by the persisted-event observatory.

The ordered ladder labels evidence quality, never model quality or causality.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FIDELITY_LADDER = (
    "declared",
    "assigned",
    "available",
    "triggered",
    "applied",
    "activated",
    "observed",
    "downstream_pathway_detected",
)
FidelityLevel = Literal[
    "declared", "assigned", "available", "triggered", "applied", "activated", "observed", "downstream_pathway_detected"
]
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class ObservatoryRequest(_Model):

    attempt_ids: list[Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]] = Field(min_length=1, max_length=100)
    xray_analysis_digest: str | None = Field(default=None, pattern=r"^(?:sha256:)?[a-f0-9]{64}$")
    source_artifact_digest: str | None = Field(default=None, pattern=r"^(?:sha256:)?[a-f0-9]{64}$")
    diagnostic_partial_mode: Literal[False] = False

    @field_validator("attempt_ids")
    @classmethod
    def unique_attempt_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("attempt_ids must be unique")
        return value


class DiagnosticMetric(_Model):
    metric_id: Identifier
    value: str | int | float | None
    numerator: int | float | None
    denominator: int | float | None
    exclusions: list[str] = Field(default_factory=list, max_length=128)


class InterventionFidelity(_Model):
    stage: FidelityLevel
    status: Literal["observed", "unknown"]
    reason: str = Field(min_length=1, max_length=16_384)


class ObservatoryReport(_Model):
    """Redacted, content-addressed report over already persisted event evidence."""

    report_id: Identifier
    report_digest: Digest
    analysis_digest: Digest
    report_artifact_digest: Digest
    claim_ceiling: str = Field(min_length=1, max_length=16_384)
    evidence_ceiling: str = Field(min_length=1, max_length=16_384)
    context_ledger: dict[str, object]
    memory_ledger: dict[str, object]
    loop_microscope: list[dict[str, object]]
    graph_microscope: dict[str, object]
    intervention_fidelity: list[InterventionFidelity]
    fidelity_ladder: list[FidelityLevel]
    fidelity_level: FidelityLevel | Literal["unknown"]
    metrics: list[DiagnosticMetric]
    attempt_ids: list[Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]]
    xray_analysis_digest: Digest | None = None
    source_artifact_digest: Digest | None = None
    limitations: list[str] = Field(default_factory=list, max_length=128)
    provider_execution_started: Literal[False] = False
    execution_started: Literal[False] = False
    network_requested: Literal[False] = False
    idempotent_replay: bool = False
