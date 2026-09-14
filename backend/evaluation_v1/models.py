"""Read-only, deterministic-first evaluation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class GraderInstallation(EvaluationModel):
    grader_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    trusted: Literal[True] = True


class GraderBinding(EvaluationModel):
    metric_id: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0)
    kind: Literal["deterministic", "qualitative"]
    installation: GraderInstallation


class HumanCalibrationReceipt(EvaluationModel):
    receipt_id: str = Field(min_length=1)
    batch_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    protocol_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_completion_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    annotator_count: int = Field(ge=3)
    resolved_conflicts: Literal[True] = True
    identity_state: Literal["verified"] = "verified"
    authority_id: str = Field(min_length=1)
    attestation_ref: str = Field(min_length=1)


class GraderPlan(EvaluationModel):
    bindings: tuple[GraderBinding, ...]
    human_calibration_receipt: HumanCalibrationReceipt | None = None
    _builtin_graders: Mapping[tuple[str, str, str], Any] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def validate_plan(self) -> GraderPlan:
        if not self.bindings:
            raise ValueError("a grader plan needs at least one grader")
        metric_ids = [binding.metric_id for binding in self.bindings]
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("grader metric_id values must be unique")
        total = sum(binding.weight for binding in self.bindings)
        if abs(total - 1.0) > 1e-9:
            raise ValueError("grader weights must allocate exactly 1.0")
        deterministic = sum(
            binding.weight
            for binding in self.bindings
            if binding.kind == "deterministic"
        )
        if deterministic < 0.70 - 1e-9:
            raise ValueError("deterministic grader weight must be at least 0.70")
        return self

    @property
    def deterministic_weight(self) -> float:
        return sum(
            binding.weight
            for binding in self.bindings
            if binding.kind == "deterministic"
        )

    @property
    def qualitative_claims_eligible(self) -> bool:
        # A plan has no observed judge output; eligibility is determined by evaluate_attempt.
        return False

    def with_builtin_graders(self, graders: Mapping[tuple[str, str, str], Any]) -> GraderPlan:
        """Return an evaluation-ready copy without registering or loading untrusted code."""
        candidate = self.model_copy(deep=False)
        object.__setattr__(candidate, "_builtin_graders", MappingProxyType(dict(graders)))
        return candidate

    def resolve_builtin(self, installation: GraderInstallation) -> Any | None:
        return self._builtin_graders.get(
            (installation.grader_id, installation.version, installation.digest)
        )


class QualitativeResult(EvaluationModel):
    """An observed judge result, not a score synthesized by the evaluation engine."""

    metric_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    evaluator_id: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    evaluator_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_evidence_ref: str = Field(min_length=1)
    output_evidence_ref: str = Field(min_length=1)
    calibration_receipt_id: str = Field(min_length=1)
    calibration_batch_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class EvaluationContext:
    """Data-only evaluator input. It deliberately has no adapter or control-plane handle."""

    artifact_refs: Mapping[str, str] = field(default_factory=dict)
    state_refs: Mapping[str, Any] = field(default_factory=dict)
    factor_assignments: Mapping[str, str | int | bool] = field(default_factory=dict)
    severe_failure_rules: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("artifact_refs", self.artifact_refs),
            ("state_refs", self.state_refs),
            ("factor_assignments", self.factor_assignments),
            ("severe_failure_rules", self.severe_failure_rules),
        ):
            if not isinstance(value, Mapping):
                raise TypeError(f"{name} must be a mapping")
            object.__setattr__(self, name, _freeze(value))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class GraderResult:
    metric_id: str
    score: float
    passed: bool
    notes: tuple[str, ...] = ()
    severe_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.metric_id or not 0.0 <= self.score <= 1.0:
            raise ValueError("grader result requires a metric_id and score in [0, 1]")


@dataclass(frozen=True)
class EvaluationResult:
    record: Any
    results: tuple[GraderResult, ...]
    hard_gate_passed: bool
    qualitative_claims_eligible: bool
    exclusions: tuple[str, ...]
