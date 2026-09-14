"""Dependency-free prospective planning for frozen binary main-effect studies.

This module evaluates declared design assumptions before provider execution. It
never estimates effects from observed results and never promotes approximate
prospective power into outcome evidence.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from protocol_v1 import ExperimentSpec, expand_design
from protocol_v1.canonical import canonical_json, sha256

ANALYSIS_PLAN_NAMESPACE = "org.scaffold-arena.analysis-plan"


class BinaryOutcomeAnalysisPlan(BaseModel):
    """Strict fixed-sample assumptions for one binary risk-difference design."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )

    schema_version: Literal["binary-outcome-v1"]
    primary_outcome: str = Field(min_length=1, max_length=128)
    estimand: Literal["risk_difference"]
    baseline_rate: float = Field(gt=0.0, lt=1.0)
    minimum_detectable_effect: float = Field(gt=0.0, lt=1.0)
    expected_direction: Literal["increase", "decrease"]
    alpha: float = Field(gt=0.0, lt=1.0)
    power: float = Field(gt=0.0, lt=1.0)
    comparison_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    intracluster_correlation: float = Field(ge=0.0, lt=1.0)
    mean_cluster_size: float = Field(ge=1.0, le=1_000_000.0)
    stopping_policy: Literal["fixed_sample"]
    missingness_policy: Literal["complete_case_with_exclusions"]

    @model_validator(mode="after")
    def validate_comparisons(self) -> BinaryOutcomeAnalysisPlan:
        if len(set(self.comparison_ids)) != len(self.comparison_ids):
            raise ValueError("comparison_ids must be unique")
        if any(not item.strip() or len(item) > 128 for item in self.comparison_ids):
            raise ValueError("comparison_ids must be non-empty bounded strings")
        return self


PlanStatus = Literal["PASS", "HOLD", "INVALID", "NOT_DECLARED"]


class AnalysisPlanAssessment(BaseModel):
    """Machine-readable preflight result; not observed research evidence."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )

    status: PlanStatus
    declared: bool
    plan_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    primary_outcome: str | None = None
    expected_control_rate: float | None = None
    expected_treatment_rate: float | None = None
    alpha_per_comparison: float | None = None
    nominal_required_per_group: int | None = Field(default=None, ge=1)
    design_effect: float = Field(ge=1.0)
    required_per_group: int | None = Field(default=None, ge=1)
    available_per_group: int = Field(ge=0)
    comparison_count: int = Field(ge=0)
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    provider_execution_started: Literal[False] = False


_INVALID_PLAN_REASON = "frozen analysis plan does not satisfy the strict binary-outcome-v1 contract"


def assess_analysis_plan(spec: ExperimentSpec) -> AnalysisPlanAssessment:
    """Assess one frozen design without running providers or reading outcomes."""

    available, design_reasons = _available_per_group(spec)
    raw = spec.extensions.get(ANALYSIS_PLAN_NAMESPACE)
    if raw is None:
        return AnalysisPlanAssessment(
            status="NOT_DECLARED",
            declared=False,
            design_effect=1.0,
            available_per_group=available,
            comparison_count=0,
            reasons=("no frozen analysis plan is declared",),
            limitations=(
                "no prospective power or minimum-detectable-effect claim is available",
            ),
        )
    if not isinstance(raw, Mapping):
        return _invalid(available, (_INVALID_PLAN_REASON,))

    try:
        plan = BinaryOutcomeAnalysisPlan.model_validate_json(
            canonical_json(dict(raw))
        )
    except (TypeError, ValueError, ValidationError):
        return _invalid(available, (_INVALID_PLAN_REASON,))

    expected_treatment = (
        plan.baseline_rate + plan.minimum_detectable_effect
        if plan.expected_direction == "increase"
        else plan.baseline_rate - plan.minimum_detectable_effect
    )
    if not 0.0 < expected_treatment < 1.0:
        return AnalysisPlanAssessment(
            status="INVALID",
            declared=True,
            plan_digest=None,
            primary_outcome=plan.primary_outcome,
            expected_control_rate=plan.baseline_rate,
            expected_treatment_rate=expected_treatment,
            design_effect=_design_effect(plan),
            available_per_group=available,
            comparison_count=len(plan.comparison_ids),
            reasons=(
                "expected treatment rate must remain strictly between zero and one",
            ),
            limitations=(
                "sample-size calculation was not attempted for an invalid expected rate",
            ),
        )

    reasons = list(design_reasons)
    limitations = [
        "prospective normal-approximation planning is not observed outcome evidence",
        "the calculation assumes the declared baseline rate and effect size rather than inferring them from fixtures or prior results",
        "available_per_group is the scheduled pooled main-effect count before missingness or execution failure",
    ]
    if plan.primary_outcome not in spec.primary_outcomes:
        reasons.append("planned primary outcome is not declared by the experiment")

    comparison_count = len(plan.comparison_ids)
    alpha_per_comparison = plan.alpha
    if comparison_count > 1:
        if spec.multiple_comparison_correction == "none":
            reasons.append("multiple planned comparisons require an explicit correction")
        else:
            alpha_per_comparison = plan.alpha / comparison_count
            if spec.multiple_comparison_correction in {
                "holm",
                "benjamini_hochberg",
            }:
                limitations.append(
                    f"{spec.multiple_comparison_correction} planning uses a conservative Bonferroni per-comparison alpha; the final registered procedure may be less conservative"
                )

    nominal = _required_per_group(
        control_rate=plan.baseline_rate,
        treatment_rate=expected_treatment,
        alpha=alpha_per_comparison,
        power=plan.power,
    )
    effect = _design_effect(plan)
    required = max(1, math.ceil(nominal * effect))

    if available < required:
        reasons.append(
            "available observations per pooled group are below the planned requirement"
        )

    expected_counts = (
        available * plan.baseline_rate,
        available * (1.0 - plan.baseline_rate),
        available * expected_treatment,
        available * (1.0 - expected_treatment),
    )
    if min(expected_counts) < 10.0:
        reasons.append(
            "normal approximation requires at least 10 expected events and non-events per pooled group"
        )

    return AnalysisPlanAssessment(
        status="HOLD" if reasons else "PASS",
        declared=True,
        plan_digest=sha256(plan.model_dump(mode="json")),
        primary_outcome=plan.primary_outcome,
        expected_control_rate=plan.baseline_rate,
        expected_treatment_rate=expected_treatment,
        alpha_per_comparison=alpha_per_comparison,
        nominal_required_per_group=nominal,
        design_effect=effect,
        required_per_group=required,
        available_per_group=available,
        comparison_count=comparison_count,
        reasons=tuple(dict.fromkeys(reasons)),
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _invalid(
    available: int,
    reasons: tuple[str, ...],
) -> AnalysisPlanAssessment:
    return AnalysisPlanAssessment(
        status="INVALID",
        declared=True,
        design_effect=1.0,
        available_per_group=available,
        comparison_count=0,
        reasons=reasons,
        limitations=(
            "no sample-size or power statement is available for an invalid plan",
        ),
    )


def _available_per_group(spec: ExperimentSpec) -> tuple[int, tuple[str, ...]]:
    reasons: list[str] = []
    if spec.design != "full":
        reasons.append("initial analysis-plan support requires a full factorial design")
    if not spec.factors:
        reasons.append("initial analysis-plan support requires at least one varied factor")
    if any(factor.kind != "binary" for factor in spec.factors):
        reasons.append("initial analysis-plan support requires binary factors")
    if reasons:
        return 0, tuple(reasons)

    treatments = len(expand_design(spec))
    if treatments < 2 or treatments % 2:
        return 0, ("full binary factorial design did not produce balanced main-effect sides",)
    units = (
        len(spec.scenario_ids)
        * len(spec.harness_ids)
        * max(len(spec.model_endpoints), 1)
        * spec.repetitions
    )
    return units * (treatments // 2), ()


def _design_effect(plan: BinaryOutcomeAnalysisPlan) -> float:
    return 1.0 + (
        plan.mean_cluster_size - 1.0
    ) * plan.intracluster_correlation


def _required_per_group(
    *,
    control_rate: float,
    treatment_rate: float,
    alpha: float,
    power: float,
) -> int:
    if not 0.0 < alpha < 1.0 or not 0.0 < power < 1.0:
        raise ValueError("alpha and power must remain strictly between zero and one")
    difference = abs(treatment_rate - control_rate)
    if difference <= 0.0:
        raise ValueError("minimum detectable effect must be positive")
    distribution = NormalDist()
    z_alpha = distribution.inv_cdf(1.0 - alpha / 2.0)
    z_power = distribution.inv_cdf(power)
    pooled = (control_rate + treatment_rate) / 2.0
    numerator = (
        z_alpha * math.sqrt(2.0 * pooled * (1.0 - pooled))
        + z_power
        * math.sqrt(
            control_rate * (1.0 - control_rate)
            + treatment_rate * (1.0 - treatment_rate)
        )
    ) ** 2
    return max(1, math.ceil(numerator / (difference**2)))


__all__ = [
    "ANALYSIS_PLAN_NAMESPACE",
    "AnalysisPlanAssessment",
    "BinaryOutcomeAnalysisPlan",
    "assess_analysis_plan",
]
