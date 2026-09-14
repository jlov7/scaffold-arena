"""Claim-boundary checks for descriptive and externally fitted analyses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class AnalysisClaimLevel(StrEnum):
    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    CONFIRMATORY_ANALYSIS_ELIGIBLE = "CONFIRMATORY_ANALYSIS_ELIGIBLE"


class MixedEffectStatus(StrEnum):
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class AdequacyRequirements:
    minimum_completed_attempts: int = 20
    minimum_clusters: int = 8
    minimum_per_arm: int = 5
    minimum_balance_ratio: float = 0.8
    minimum_manipulation_fidelity: float = 0.95
    minimum_trace_completeness: float = 0.95

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in (self.minimum_completed_attempts, self.minimum_clusters, self.minimum_per_arm)):
            raise ValueError("attempt, cluster, and per-arm requirements must be positive integers")
        for value in (self.minimum_balance_ratio, self.minimum_manipulation_fidelity, self.minimum_trace_completeness):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or not 0 <= value <= 1:
                raise ValueError("fractional requirements must be finite values in [0, 1]")


@dataclass(frozen=True)
class AdequacyInput:
    completed_attempts: int
    cluster_count: int
    control_attempts: int
    treatment_attempts: int
    manipulation_fidelity: float
    trace_completeness: float
    preregistered_design: bool = False
    treatment_manipulation_fidelity_pass: bool = False
    comparison_invariants_pass: bool = False
    evaluator_independence_pass: bool = False
    sealed_or_held_out_tasks_pass: bool = False
    external_fitted_model_result: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (self.completed_attempts, self.cluster_count, self.control_attempts, self.treatment_attempts)):
            raise ValueError("count fields must be non-negative integers")
        for value in (self.manipulation_fidelity, self.trace_completeness):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value) or not 0 <= value <= 1:
                raise ValueError("fidelity and completeness must be finite values in [0, 1]")
        if self.external_fitted_model_result is not None and not self.external_fitted_model_result.strip():
            raise ValueError("external fitted-model result must be non-empty when supplied")
        design_gates = (
            self.preregistered_design,
            self.treatment_manipulation_fidelity_pass,
            self.comparison_invariants_pass,
            self.evaluator_independence_pass,
            self.sealed_or_held_out_tasks_pass,
        )
        if any(type(value) is not bool for value in design_gates):
            raise ValueError("design and evidence gates must be bool")


@dataclass(frozen=True)
class AdequacyResult:
    claim_level: AnalysisClaimLevel
    reasons: tuple[str, ...]
    balance_ratio: float
    mixed_effect_status: MixedEffectStatus
    external_fitted_model_result: str | None


DEFAULT_REQUIREMENTS = AdequacyRequirements()


def assess_analysis_adequacy(inputs: AdequacyInput, requirements: AdequacyRequirements = DEFAULT_REQUIREMENTS) -> AdequacyResult:
    reasons: list[str] = []
    if inputs.completed_attempts < requirements.minimum_completed_attempts:
        reasons.append("insufficient completed attempts")
    if inputs.cluster_count < requirements.minimum_clusters:
        reasons.append("insufficient task-cluster diversity")
    if min(inputs.control_attempts, inputs.treatment_attempts) < requirements.minimum_per_arm:
        reasons.append("insufficient attempts in one or both arms")
    balance_ratio = 0.0 if max(inputs.control_attempts, inputs.treatment_attempts) == 0 else min(inputs.control_attempts, inputs.treatment_attempts) / max(inputs.control_attempts, inputs.treatment_attempts)
    if balance_ratio < requirements.minimum_balance_ratio:
        reasons.append("insufficient arm balance")
    if inputs.manipulation_fidelity < requirements.minimum_manipulation_fidelity:
        reasons.append("insufficient manipulation fidelity")
    if inputs.trace_completeness < requirements.minimum_trace_completeness:
        reasons.append("insufficient trace completeness")
    for passed, reason in (
        (inputs.preregistered_design, "design was not preregistered"),
        (inputs.treatment_manipulation_fidelity_pass, "treatment/manipulation fidelity gate failed"),
        (inputs.evaluator_independence_pass, "evaluator independence gate failed"),
        (inputs.sealed_or_held_out_tasks_pass, "sealed or held-out task gate failed"),
    ):
        if not passed:
            reasons.append(reason)
    # `comparison_invariants_pass` is a legacy declaration, not a derived,
    # persisted cross-arm evidence check. No such check exists in v1, so no
    # caller can raise the claim ceiling by asserting this boolean.
    reasons.append(
        "derived persisted comparison-invariant evidence is unavailable; caller-supplied comparison_invariants_pass cannot establish eligibility"
    )
    claim_level = AnalysisClaimLevel.DESCRIPTIVE_ONLY if reasons else AnalysisClaimLevel.CONFIRMATORY_ANALYSIS_ELIGIBLE
    if inputs.external_fitted_model_result is not None:
        reasons.append("caller-supplied mixed-effect results are legacy descriptive evidence and never claim-eligible")
        claim_level = AnalysisClaimLevel.DESCRIPTIVE_ONLY
    return AdequacyResult(claim_level, tuple(reasons), balance_ratio, MixedEffectStatus.NOT_RUN, None)
