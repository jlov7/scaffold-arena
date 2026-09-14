"""Strict, provider-free contracts for Arena Forge, planning, and process safety.

These contracts intentionally model *records about* proposals and evaluations.
They do not carry source text, credentials, executable patches, or an execution
instruction.  Content is represented by immutable digests or redacted manifests.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=512)]
LongText = Annotated[str, Field(min_length=1, max_length=4096)]

Sensitivity = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "SECRET"]
ForgeOutcome = Literal["ADMITTED", "REJECTED", "QUARANTINED", "INCONCLUSIVE"]
ApprovalDecision = Literal["APPROVED", "REJECTED"]
PlannerMode = Literal["exploratory", "confirmatory"]
SafetyState = Literal["NOT_OBSERVED", "BLOCKED", "DETECTED", "UNKNOWN"]
SafetyVerdict = Literal["PASS", "HOLD", "FAIL"]


class ForgeModel(BaseModel):
    """Reject unknown fields and coercion at the public M4 boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("finite values are required")
    return value


class MechanismChange(ForgeModel):
    """The sole change Forge is allowed to propose for one candidate."""

    mechanism_id: Identifier
    base_mechanism_digest: Digest
    candidate_mechanism_digest: Digest
    patch_or_config_digest: Digest
    declared_change_count: Literal[1] = 1

    @model_validator(mode="after")
    def one_actual_change(self) -> "MechanismChange":
        if self.base_mechanism_digest == self.candidate_mechanism_digest:
            raise ValueError("the declared mechanism must actually change")
        return self


class FalsifiablePrediction(ForgeModel):
    metric_id: Identifier
    direction: Literal["increase", "decrease", "no_more_than"]
    threshold: Annotated[float, Field(ge=0.0, le=1_000_000)]
    prediction_digest: Digest

    @field_validator("threshold")
    @classmethod
    def finite_threshold(cls, value: float) -> float:
        return _finite(value)


class ExpectedTradeoff(ForgeModel):
    quality: Literal["improve", "regress", "neutral", "unknown"]
    safety: Literal["improve", "regress", "neutral", "unknown"]
    cost: Literal["increase", "decrease", "neutral", "unknown"]
    latency: Literal["increase", "decrease", "neutral", "unknown"]
    rationale_digest: Digest


class RollbackBinding(ForgeModel):
    rollback_id: Identifier
    rollback_digest: Digest
    recovery_plan_digest: Digest


class ForgeProposal(ForgeModel):
    """Untrusted candidate mutation. It can never request execution or merge."""

    schema_version: Literal["scaffold-arena.forge-proposal/1"] = "scaffold-arena.forge-proposal/1"
    proposal_id: Identifier
    proposer_identity: Identifier
    source_provenance_digest: Digest
    base_genome_digest: Digest
    candidate_genome_digest: Digest
    mechanism_change: MechanismChange
    falsifiable_prediction: FalsifiablePrediction
    expected_tradeoff: ExpectedTradeoff
    triggering_evidence_digests: list[Digest] = Field(min_length=1, max_length=64)
    rollback: RollbackBinding
    requested_claim_scope: Literal["fixture_contract", "recorded_observation", "product_control"]
    untrusted: Literal[True] = True
    execution_requested: Literal[False] = False
    automatic_merge_requested: Literal[False] = False
    self_evaluation_requested: Literal[False] = False
    scalar_optimization_requested: Literal[False] = False

    @model_validator(mode="after")
    def proposal_is_bounded(self) -> "ForgeProposal":
        if self.base_genome_digest == self.candidate_genome_digest:
            raise ValueError("base and candidate Genome digests must differ")
        if len(self.triggering_evidence_digests) != len(set(self.triggering_evidence_digests)):
            raise ValueError("triggering evidence digests must be unique")
        return self


class ForgeApproval(ForgeModel):
    """Human or policy decision; it cannot grant execution or promotion."""

    schema_version: Literal["scaffold-arena.forge-approval/1"] = "scaffold-arena.forge-approval/1"
    proposal_digest: Digest
    approver_identity: Identifier
    authority_kind: Literal["human", "policy"]
    decision: ApprovalDecision
    policy_digest: Digest
    decision_evidence_digest: Digest
    execution_authorized: Literal[False] = False
    merge_authorized: Literal[False] = False


class EvaluationCohorts(ForgeModel):
    """Holdout contents stay sealed: only its manifest/runner receipts bind it."""

    cohort_partition_digest: Digest
    development_item_digests: list[Digest] = Field(min_length=1, max_length=512)
    sealed_holdout_manifest_digest: Digest
    sealed_holdout_runner_receipt_digest: Digest
    safety_item_digests: list[Digest] = Field(min_length=1, max_length=512)
    transfer_cohorts: list["TransferCohort"] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def nonsealed_cohorts_are_disjoint(self) -> "EvaluationCohorts":
        groups: list[set[str]] = [set(self.development_item_digests), set(self.safety_item_digests)]
        groups.extend(set(group.item_digests) for group in self.transfer_cohorts)
        if any(len(group.item_digests) != len(set(group.item_digests)) for group in self.transfer_cohorts):
            raise ValueError("transfer cohort item digests must be unique")
        if len(self.development_item_digests) != len(groups[0]) or len(self.safety_item_digests) != len(groups[1]):
            raise ValueError("development and safety item digests must be unique")
        for index, left in enumerate(groups):
            if any(left & right for right in groups[index + 1:]):
                raise ValueError("development, safety, and transfer cohorts must be disjoint")
        return self


class TransferCohort(ForgeModel):
    cohort_id: Identifier
    item_digests: list[Digest] = Field(min_length=1, max_length=512)


class FrozenEvaluationPlan(ForgeModel):
    experiment_plan_digest: Digest
    analysis_plan_digest: Digest
    evaluator_configuration_digest: Digest
    stopping_rule_digest: Digest
    cancellation_policy_digest: Digest
    recovery_policy_digest: Digest
    matched_compute_budget_digest: Digest
    deterministic_score_weight: Annotated[float, Field(ge=0.7, le=1.0)]
    exploratory_adaptation: Literal[False] = False
    frozen: Literal[True] = True

    @field_validator("deterministic_score_weight")
    @classmethod
    def finite_weight(cls, value: float) -> float:
        return _finite(value)


class EffectWithUncertainty(ForgeModel):
    metric_id: Identifier
    state: Literal["observed", "unknown"]
    point_estimate: float | None = None
    ci95_low: float | None = None
    ci95_high: float | None = None
    minimum_detectable_effect: Annotated[float, Field(ge=0.0, le=1_000_000)]

    @field_validator("point_estimate", "ci95_low", "ci95_high", "minimum_detectable_effect")
    @classmethod
    def finite_effects(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value)

    @model_validator(mode="after")
    def unknowns_are_not_zeros(self) -> "EffectWithUncertainty":
        values = (self.point_estimate, self.ci95_low, self.ci95_high)
        if self.state == "unknown" and any(value is not None for value in values):
            raise ValueError("unknown effects must leave estimates and intervals null")
        if self.state == "observed" and self.point_estimate is None:
            raise ValueError("observed effects require a point estimate")
        return self


class EvaluationFailure(ForgeModel):
    failure_id: Identifier
    severity: Literal["low", "moderate", "severe"]
    evidence_digest: Digest
    disposition: Literal["retained", "quarantined", "blocks_admission"]


class UsageAndCost(ForgeModel):
    state: Literal["observed", "unknown"]
    usage_digest: Digest | None = None
    cost_usd: Annotated[float, Field(ge=0.0, le=1_000_000)] | None = None
    latency_ms: Annotated[int, Field(ge=0, le=86_400_000)] | None = None

    @field_validator("cost_usd")
    @classmethod
    def finite_cost(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value)

    @model_validator(mode="after")
    def usage_is_complete_or_unknown(self) -> "UsageAndCost":
        values = (self.usage_digest, self.cost_usd, self.latency_ms)
        if self.state == "unknown" and any(value is not None for value in values):
            raise ValueError("unknown usage must keep cost and latency null")
        if self.state == "observed" and any(value is None for value in values):
            raise ValueError("observed usage requires usage digest, cost, and latency")
        return self


class MatchedControl(ForgeModel):
    control_kind: Literal["random_search", "heuristic_edits", "no_change", "matched_compute_test_time_search"]
    control_genome_digest: Digest
    result_digest: Digest
    compute_budget_digest: Digest
    evaluator_configuration_digest: Digest


class AdmissionRecord(ForgeModel):
    authority_kind: Literal["human", "policy"]
    admitting_identity: Identifier
    policy_digest: Digest
    decision_evidence_digest: Digest
    outcome: ForgeOutcome
    merge_authorized: Literal[False] = False
    execution_authorized: Literal[False] = False


class EvaluationWorkflow(ForgeModel):
    """Recorded lifecycle evidence; it is never an instruction to resume work."""

    state: Literal["completed", "interrupted", "cancelled", "recovered"]
    interruption_evidence_digest: Digest | None = None
    recovery_evidence_digest: Digest | None = None
    rollback_state: Literal["not_needed", "recorded"] = "not_needed"
    rollback_evidence_digest: Digest | None = None

    @model_validator(mode="after")
    def recovery_and_rollback_are_evidenced(self) -> "EvaluationWorkflow":
        if self.state in {"interrupted", "cancelled"}:
            if self.interruption_evidence_digest is None or self.recovery_evidence_digest is not None:
                raise ValueError("interrupted and cancelled work require interruption evidence and cannot claim recovery")
        elif self.state == "recovered":
            if self.interruption_evidence_digest is None or self.recovery_evidence_digest is None:
                raise ValueError("recovered work requires both interruption and recovery evidence")
        elif self.interruption_evidence_digest is not None or self.recovery_evidence_digest is not None:
            raise ValueError("completed work cannot carry interruption or recovery evidence")
        if self.rollback_state == "recorded" and self.rollback_evidence_digest is None:
            raise ValueError("a recorded rollback requires an evidence digest")
        if self.rollback_state == "not_needed" and self.rollback_evidence_digest is not None:
            raise ValueError("rollback evidence requires a recorded rollback state")
        return self


class ForgeEvaluation(ForgeModel):
    """Captured evaluation evidence, never an executor instruction."""

    schema_version: Literal["scaffold-arena.forge-evaluation/1"] = "scaffold-arena.forge-evaluation/1"
    evaluation_id: Identifier
    proposal_digest: Digest
    evaluator_identity: Identifier
    evaluator_identity_digest: Digest
    cohorts: EvaluationCohorts
    frozen_plan: FrozenEvaluationPlan
    result_evidence_digests: list[Digest] = Field(min_length=1, max_length=128)
    effects: list[EffectWithUncertainty] = Field(min_length=1, max_length=32)
    failures: list[EvaluationFailure] = Field(default_factory=list, max_length=128)
    failure_manifest_digest: Digest
    usage: UsageAndCost
    matched_controls: list[MatchedControl] = Field(min_length=4, max_length=4)
    process_safety_report_digest: Digest
    workflow: EvaluationWorkflow
    outcome: ForgeOutcome
    admission: AdmissionRecord
    sealed_holdout_inspected: Literal[False] = False
    evaluator_changed: Literal[False] = False
    failures_erased: Literal[False] = False
    self_graded: Literal[False] = False
    self_promoted: Literal[False] = False
    automatic_merge: Literal[False] = False
    execution_started: Literal[False] = False
    network_requested: Literal[False] = False

    @model_validator(mode="after")
    def evaluation_is_separated_and_matched(self) -> "ForgeEvaluation":
        if len(self.result_evidence_digests) != len(set(self.result_evidence_digests)):
            raise ValueError("result evidence digests must be unique")
        kinds = [control.control_kind for control in self.matched_controls]
        expected = {"random_search", "heuristic_edits", "no_change", "matched_compute_test_time_search"}
        if set(kinds) != expected or len(kinds) != len(set(kinds)):
            raise ValueError("all four unique matched controls are required")
        if any(control.compute_budget_digest != self.frozen_plan.matched_compute_budget_digest for control in self.matched_controls):
            raise ValueError("every control must bind the frozen matched-compute budget")
        if any(control.evaluator_configuration_digest != self.frozen_plan.evaluator_configuration_digest for control in self.matched_controls):
            raise ValueError("every control must bind the frozen evaluator configuration")
        if self.admission.outcome != self.outcome:
            raise ValueError("admission outcome must match the evaluation outcome")
        if self.workflow.state in {"interrupted", "cancelled"} and self.outcome == "ADMITTED":
            raise ValueError("interrupted or cancelled work cannot be admitted")
        return self


class EvolutionReceipt(ForgeModel):
    schema_version: Literal["scaffold-arena.evolution-receipt/1"]
    receipt_id: Identifier
    receipt_digest: Digest
    receipt_artifact_digest: Digest
    proposal_digest: Digest
    approval_digest: Digest
    evaluation_digest: Digest
    outcome: ForgeOutcome
    evaluator_identity: Identifier
    admitting_identity: Identifier
    claim_ceiling: ShortText
    immutable: Literal[True] = True
    execution_started: Literal[False] = False
    automatic_merge: Literal[False] = False
    idempotent_replay: bool = False


class PlannerMechanism(ForgeModel):
    mechanism_id: Identifier
    uncertainty: Annotated[float, Field(ge=0.0, le=1.0)]
    expected_effect: Annotated[float, Field(ge=0.0, le=1_000_000)]
    interaction_uncertainty: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0

    @field_validator("uncertainty", "expected_effect", "interaction_uncertainty")
    @classmethod
    def finite_values(cls, value: float) -> float:
        return _finite(value)


class PlannerCoverage(ForgeModel):
    coverage_id: Identifier
    fraction: Annotated[float, Field(gt=0.0, le=1.0)]

    @field_validator("fraction")
    @classmethod
    def finite_fraction(cls, value: float) -> float:
        return _finite(value)


class PlannerPriorEvidence(ForgeModel):
    evidence_digest: Digest
    mechanism_id: Identifier
    evidence_strength: Annotated[float, Field(ge=0.0, le=1.0)]

    @field_validator("evidence_strength")
    @classmethod
    def finite_strength(cls, value: float) -> float:
        return _finite(value)


class CandidateDesign(ForgeModel):
    design_id: Identifier
    mechanism_id: Identifier
    coverage_ids: list[Identifier] = Field(min_length=1, max_length=32)
    cost_per_attempt_usd: Annotated[float, Field(gt=0.0, le=1_000_000)]
    minimum_attempts: Annotated[int, Field(ge=1, le=10_000)]
    maximum_attempts: Annotated[int, Field(ge=1, le=10_000)]
    risk: Annotated[float, Field(ge=0.0, le=1.0)]
    assumptions: list[ShortText] = Field(min_length=1, max_length=32)

    @field_validator("cost_per_attempt_usd", "risk")
    @classmethod
    def finite_design_values(cls, value: float) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def valid_attempt_interval(self) -> "CandidateDesign":
        if self.maximum_attempts < self.minimum_attempts:
            raise ValueError("maximum attempts must be at least minimum attempts")
        if len(self.coverage_ids) != len(set(self.coverage_ids)):
            raise ValueError("coverage ids must be unique")
        return self


class NextBestExperimentRequest(ForgeModel):
    schema_version: Literal["scaffold-arena.next-best-experiment/1"] = "scaffold-arena.next-best-experiment/1"
    request_id: Identifier
    mode: PlannerMode
    mechanisms: list[PlannerMechanism] = Field(min_length=1, max_length=128)
    coverage: list[PlannerCoverage] = Field(min_length=1, max_length=128)
    prior_evidence: list[PlannerPriorEvidence] = Field(default_factory=list, max_length=256)
    candidate_designs: list[CandidateDesign] = Field(min_length=1, max_length=128)
    minimum_detectable_effect: Annotated[float, Field(gt=0.0, le=1_000_000)]
    remaining_budget_usd: Annotated[float, Field(gt=0.0, le=1_000_000)]
    maximum_risk: Annotated[float, Field(ge=0.0, le=1.0)]
    frozen_analysis_plan_digest: Digest | None = None
    exploratory_adaptation: bool = False
    source_evidence_digests: list[Digest] = Field(min_length=1, max_length=128)
    execution_requested: Literal[False] = False
    automatic_admission_requested: Literal[False] = False

    @field_validator("minimum_detectable_effect", "remaining_budget_usd", "maximum_risk")
    @classmethod
    def finite_request_values(cls, value: float) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def mode_remains_separate(self) -> "NextBestExperimentRequest":
        mechanisms = {item.mechanism_id for item in self.mechanisms}
        coverage = {item.coverage_id for item in self.coverage}
        if len(mechanisms) != len(self.mechanisms) or len(coverage) != len(self.coverage):
            raise ValueError("mechanism and coverage ids must be unique")
        if any(design.mechanism_id not in mechanisms or not set(design.coverage_ids) <= coverage for design in self.candidate_designs):
            raise ValueError("candidate designs must reference declared mechanisms and coverage")
        if self.mode == "confirmatory" and (self.frozen_analysis_plan_digest is None or self.exploratory_adaptation):
            raise ValueError("confirmatory planning requires a frozen analysis plan and no exploratory adaptation")
        if self.mode == "exploratory" and self.frozen_analysis_plan_digest is not None:
            raise ValueError("exploratory planning must not present a frozen confirmatory analysis plan")
        return self


class CostInterval(ForgeModel):
    lower_usd: Annotated[float, Field(ge=0.0, le=1_000_000)]
    upper_usd: Annotated[float, Field(ge=0.0, le=1_000_000)]

    @field_validator("lower_usd", "upper_usd")
    @classmethod
    def finite_costs(cls, value: float) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def ordered_interval(self) -> "CostInterval":
        if self.upper_usd < self.lower_usd:
            raise ValueError("cost interval upper bound must be at least lower bound")
        return self


class PlannerRecommendation(ForgeModel):
    rank: Annotated[int, Field(ge=1)]
    proposed_design: CandidateDesign
    expected_information_gain: Annotated[float, Field(ge=0.0, le=1_000_000)]
    attempts: Annotated[int, Field(ge=1, le=10_000)]
    cost_interval: CostInterval
    risk: Annotated[float, Field(ge=0.0, le=1.0)]
    assumptions: list[ShortText]
    claim_ceiling: ShortText
    alternatives: list[Identifier]

    @field_validator("expected_information_gain", "risk")
    @classmethod
    def finite_rec_values(cls, value: float) -> float:
        return _finite(value)


class ExcludedDesign(ForgeModel):
    design_id: Identifier
    reason: ShortText


class NextBestExperimentReport(ForgeModel):
    schema_version: Literal["scaffold-arena.next-best-experiment-report/1"]
    report_id: Identifier
    report_digest: Digest
    report_artifact_digest: Digest
    request_digest: Digest
    mode: PlannerMode
    verdict: Literal["READY", "HOLD"]
    recommendations: list[PlannerRecommendation]
    excluded_designs: list[ExcludedDesign]
    claim_ceiling: ShortText
    execution_started: Literal[False] = False
    network_requested: Literal[False] = False
    idempotent_replay: bool = False


class ProcessSafetyPolicy(ForgeModel):
    policy_digest: Digest
    maximum_sensitivity: Sensitivity
    allowed_tool_digests: list[Digest] = Field(default_factory=list, max_length=128)
    allow_external_egress: Literal[False] = False
    maximum_delegation_depth: Annotated[int, Field(ge=0, le=16)] = 0
    secret_retention: Literal["digests_and_redacted_manifests_only"] = "digests_and_redacted_manifests_only"
    required_cleanup: Literal[True] = True


class InformationFlow(ForgeModel):
    flow_id: Identifier
    source: Literal["context", "model", "tool", "memory", "artifact", "external"]
    destination: Literal["context", "model", "tool", "memory", "artifact", "external"]
    sensitivity: Sensitivity
    content_digest: Digest | None = None
    redacted_manifest_digest: Digest | None = None
    tool_digest: Digest | None = None
    delegation_depth: Annotated[int, Field(ge=0, le=16)] = 0

    @model_validator(mode="after")
    def digest_only_flow(self) -> "InformationFlow":
        if self.content_digest is None and self.redacted_manifest_digest is None:
            raise ValueError("information flows require a content digest or redacted manifest digest")
        if self.sensitivity in {"RESTRICTED", "SECRET"} and self.redacted_manifest_digest is None:
            raise ValueError("restricted and secret flows require a redacted manifest digest")
        return self


class ProcessSafetyOutcome(ForgeModel):
    outcome_type: Literal[
        "unnecessary_sensitive_data_access",
        "prohibited_tool",
        "permission_escalation",
        "network_egress",
        "secret_exposure",
        "unsafe_intermediate_artifact",
        "policy_bypassing_retry",
        "sensitive_persistent_memory",
        "trace_log_leakage",
        "cleanup_failure",
    ]
    state: SafetyState
    evidence_digest: Digest


class PlanTransition(ForgeModel):
    from_state: Literal["DRAFT", "PENDING_APPROVAL", "APPROVED", "EVALUATED", "ADMITTED", "REJECTED", "QUARANTINED", "INCONCLUSIVE"]
    to_state: Literal["PENDING_APPROVAL", "APPROVED", "REJECTED", "EVALUATED", "ADMITTED", "QUARANTINED", "INCONCLUSIVE"]
    transition_digest: Digest


class ProcessSafetyRequest(ForgeModel):
    schema_version: Literal["scaffold-arena.process-safety/1"] = "scaffold-arena.process-safety/1"
    request_id: Identifier
    policy: ProcessSafetyPolicy
    flows: list[InformationFlow] = Field(min_length=1, max_length=512)
    outcomes: list[ProcessSafetyOutcome] = Field(min_length=10, max_length=10)
    transitions: list[PlanTransition] = Field(min_length=1, max_length=32)
    cleanup_receipt_digest: Digest | None = None
    source_manifest_digest: Digest
    execution_started: Literal[False] = False
    network_requested: Literal[False] = False

    @model_validator(mode="after")
    def all_safety_outcomes_are_present(self) -> "ProcessSafetyRequest":
        required = {
            "unnecessary_sensitive_data_access", "prohibited_tool", "permission_escalation", "network_egress",
            "secret_exposure", "unsafe_intermediate_artifact", "policy_bypassing_retry", "sensitive_persistent_memory",
            "trace_log_leakage", "cleanup_failure",
        }
        observed = [item.outcome_type for item in self.outcomes]
        if set(observed) != required or len(observed) != len(required):
            raise ValueError("every first-class process-safety outcome is required exactly once")
        if self.policy.required_cleanup and self.cleanup_receipt_digest is None:
            raise ValueError("required cleanup needs a digest-bound cleanup receipt")
        return self


class ProcessSafetyCheck(ForgeModel):
    check_id: Identifier
    verdict: SafetyVerdict
    detail: ShortText


class ProcessSafetyReport(ForgeModel):
    schema_version: Literal["scaffold-arena.process-safety-report/1"]
    report_id: Identifier
    report_digest: Digest
    report_artifact_digest: Digest
    request_digest: Digest
    verdict: SafetyVerdict
    checks: list[ProcessSafetyCheck]
    retained_manifest_digests: list[Digest]
    claim_ceiling: ShortText
    raw_sensitive_content_retained: Literal[False] = False
    execution_started: Literal[False] = False
    network_requested: Literal[False] = False
    idempotent_replay: bool = False
