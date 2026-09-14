"""Public, strict contracts for durable blind review."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evaluation_v1 import GraderPlan
from protocol_v1.canonical import canonical_json, sha256

_BLIND_FORBIDDEN = frozenset({"treatment", "harness", "factor", "scaffold", "adapter", "control_plane", "controlplane"})


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvaluatorIdentity(ReviewModel):
    evaluator_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class AnnotationItem(ReviewModel):
    item_id: str = Field(min_length=1, max_length=128)
    attempt_id: str = Field(min_length=1, max_length=64)


class RubricDimension(ReviewModel):
    metric_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=4000)
    anchor_0: str = Field(min_length=1, max_length=4000)
    anchor_1: str = Field(min_length=1, max_length=4000)


class HumanRubric(ReviewModel):
    rubric_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    dimensions: tuple[RubricDimension, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rubric(self) -> HumanRubric:
        if len({dimension.metric_id for dimension in self.dimensions}) != len(self.dimensions):
            raise ValueError("rubric metric_id values must be unique")
        strings = [self.rubric_id]
        for dimension in self.dimensions:
            strings.extend((dimension.metric_id, dimension.instruction, dimension.anchor_0, dimension.anchor_1))
        if any(token in value.casefold() for value in strings for token in _BLIND_FORBIDDEN):
            raise ValueError("rubric cannot expose treatment or scaffold identifiers")
        if self.digest != sha256(self.model_dump(mode="json", exclude={"digest"})):
            raise ValueError("rubric digest does not match canonical rubric content")
        return self


class AnnotationBatch(ReviewModel):
    batch_id: str = Field(min_length=1, max_length=64)
    protocol_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluator: EvaluatorIdentity
    grader_plan: GraderPlan
    rubric: HumanRubric
    annotator_pseudonyms: tuple[str, ...] = Field(min_length=3)
    items: tuple[AnnotationItem, ...] = Field(min_length=1)

    @field_validator("evaluator", mode="before")
    @classmethod
    def validate_evaluator_json(cls, value: object) -> EvaluatorIdentity:
        if isinstance(value, EvaluatorIdentity):
            return value
        return EvaluatorIdentity.model_validate_json(canonical_json(value))

    @field_validator("grader_plan", mode="before")
    @classmethod
    def validate_grader_plan_json(cls, value: object) -> GraderPlan:
        if isinstance(value, GraderPlan):
            return value
        return GraderPlan.model_validate_json(canonical_json(value))

    @field_validator("rubric", mode="before")
    @classmethod
    def validate_rubric_json(cls, value: object) -> HumanRubric:
        if isinstance(value, HumanRubric):
            return value
        return HumanRubric.model_validate_json(canonical_json(value))

    @field_validator("annotator_pseudonyms", mode="before")
    @classmethod
    def validate_pseudonyms_json(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            return tuple(value)
        return value  # type: ignore[return-value]

    @field_validator("items", mode="before")
    @classmethod
    def validate_items_json(cls, value: object) -> tuple[AnnotationItem, ...]:
        if not isinstance(value, list):
            return value  # type: ignore[return-value]
        return tuple(
            item if isinstance(item, AnnotationItem) else AnnotationItem.model_validate_json(canonical_json(item))
            for item in value
        )

    @model_validator(mode="after")
    def validate_batch(self) -> AnnotationBatch:
        if any(not value or len(value) > 128 for value in self.annotator_pseudonyms) or len(set(self.annotator_pseudonyms)) != len(self.annotator_pseudonyms):
            raise ValueError("annotator pseudonyms must be distinct non-empty values")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("batch item_id values must be unique")
        qualitative = {binding.metric_id for binding in self.grader_plan.bindings if binding.kind == "qualitative"}
        dimensions = {dimension.metric_id for dimension in self.rubric.dimensions}
        if dimensions != qualitative:
            raise ValueError("rubric dimensions must exactly match qualitative grader-plan metrics")
        return self


class AnnotationSubmission(ReviewModel):
    assignment_id: str = Field(min_length=1, max_length=64)
    annotator_pseudonym: str = Field(min_length=1, max_length=128)
    dimension_scores: dict[str, float] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scores(self) -> AnnotationSubmission:
        if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in self.dimension_scores.values()):
            raise ValueError("dimension scores must be finite values in [0, 1]")
        return self


class AdjudicationSubmission(ReviewModel):
    item_id: str = Field(min_length=1, max_length=128)
    adjudicator_pseudonym: str = Field(min_length=1, max_length=128)
    final_scores: dict[str, float] = Field(min_length=1)
    decision: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1)
    evidence_artifact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_scores(self) -> AdjudicationSubmission:
        if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in self.final_scores.values()):
            raise ValueError("final dimension scores must be finite values in [0, 1]")
        return self


class CalibrationAnnotationResult(ReviewModel):
    """Portable, protocol-v1 annotation record for the release-facing packet."""

    target_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    assignment_id: str = Field(min_length=1, max_length=64)
    annotator_pseudonym: str = Field(min_length=1, max_length=128)
    blind_to_scaffold: Literal[True] = True
    dimension_scores: dict[str, float] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scores(self) -> CalibrationAnnotationResult:
        if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in self.dimension_scores.values()):
            raise ValueError("dimension scores must be finite values in [0, 1]")
        return self


class CalibrationAdjudicationResult(ReviewModel):
    """Portable, protocol-v1 adjudication record bound to blinded packet evidence."""

    target_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    adjudicator_pseudonym: str = Field(min_length=1, max_length=128)
    final_scores: dict[str, float] = Field(min_length=1)
    decision: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1)
    evidence_artifact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_scores(self) -> CalibrationAdjudicationResult:
        if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in self.final_scores.values()):
            raise ValueError("final dimension scores must be finite values in [0, 1]")
        return self
