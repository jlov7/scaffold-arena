"""Strict provider-free contracts for Counterfactual Replay and Harness CI."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")]
Text = Annotated[str, Field(min_length=1, max_length=512)]
EvidenceMaturity = Literal[
    "temporal_correlation", "diagnostic_divergence", "paired_replay",
    "replicated_intervention", "confirmatory_eligibility",
]
EvidenceState = Literal["observed", "unknown", "ineligible"]
Verdict = Literal["PASS", "HOLD", "FAIL"]
ReplayMode = Literal["fixture", "recorded", "live"]
ValueState = Literal["observed", "unknown"]
FidelityLevel = Literal[
    "declared", "assigned", "available", "triggered", "applied", "activated",
    "observed", "downstream_pathway_detected",
]
ProcessSafety = Literal["pass", "fail", "unknown"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("finite values are required")
    return value


class ReplayBinding(_Model):
    """All branch-invariant pre-divergence inputs are bound once, not per branch."""

    checkpoint_digest: Digest
    initial_state_digest: Digest
    pre_divergence_trace_digest: Digest
    environment_digest: Digest
    dependencies_digest: Digest
    model_identity_digest: Digest
    runtime_identity_digest: Digest
    task_pack_digest: Digest
    evaluator_digest: Digest
    evaluator_configuration_digest: Digest
    evaluation_configuration_digest: Digest
    evaluator_blinded: Literal[True] = True
    base_genome_digest: Digest
    candidate_genome_digest: Digest

    @model_validator(mode="after")
    def distinct_candidate_and_evaluator(self) -> ReplayBinding:
        if self.base_genome_digest == self.candidate_genome_digest:
            raise ValueError("base and candidate Genome digests must differ")
        if self.evaluator_digest in {self.base_genome_digest, self.candidate_genome_digest}:
            raise ValueError("the evaluator must not reuse a branch Genome binding")
        if self.evaluator_configuration_digest in {
            self.base_genome_digest,
            self.candidate_genome_digest,
            self.evaluator_digest,
        }:
            raise ValueError("evaluator and evaluator configuration must be separately bound")
        return self


class MechanismIntervention(_Model):
    mechanism_id: Identifier
    base_mechanism_digest: Digest
    candidate_mechanism_digest: Digest
    intervention_spec_digest: Digest
    applied_control_receipt_digest: Digest
    declared_change_count: Literal[1] = 1

    @model_validator(mode="after")
    def actual_one_change(self) -> MechanismIntervention:
        if self.base_mechanism_digest == self.candidate_mechanism_digest:
            raise ValueError("the declared mechanism must change")
        return self


class SemanticMechanismDiff(_Model):
    source_diff_digest: Digest
    changed_mechanism_ids: list[Identifier] = Field(min_length=1, max_length=1)
    recommended_packs: list[Identifier] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique_packs(self) -> SemanticMechanismDiff:
        if len(self.recommended_packs) != len(set(self.recommended_packs)):
            raise ValueError("recommended packs must be unique")
        return self


class CohortAllocation(_Model):
    allocation_digest: Digest
    allocation_kind: Literal["paired", "randomized_paired"]
    development_item_digests: list[Digest] = Field(min_length=1, max_length=512)
    holdout_item_digests: list[Digest] = Field(min_length=1, max_length=512)
    replay_item_digests: list[Digest] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def cohorts_are_disjoint(self) -> CohortAllocation:
        development, holdout, replay = map(set, (self.development_item_digests, self.holdout_item_digests, self.replay_item_digests))
        if len(development) != len(self.development_item_digests) or len(holdout) != len(self.holdout_item_digests) or len(replay) != len(self.replay_item_digests):
            raise ValueError("cohort item digests must be unique")
        if development & holdout or replay & holdout:
            raise ValueError("holdout overlap is forbidden")
        if not replay <= development:
            raise ValueError("replay items must be predeclared development-cohort items")
        return self


class ReplayAnalysisPlan(_Model):
    preregistration_digest: Digest
    stopping_rule_digest: Digest
    exclusion_rule_digest: Digest
    primary_endpoint: Identifier
    planned_repetitions: Annotated[int, Field(ge=1, le=512)]
    deterministic_score_weight: Annotated[float, Field(ge=0.7, le=1.0)]
    evaluator_blinded: Literal[True] = True
    confirmatory_holdout_declared: bool = False
    causal_claim_requested: Literal[False] = False

    @field_validator("deterministic_score_weight")
    @classmethod
    def finite_weight(cls, value: float) -> float:
        return _finite(value)


class LiveAuthorization(_Model):
    """Attestation only: credentials themselves are never supplied or stored."""

    credentials_configured: Literal[True]
    budget_usd: Annotated[float, Field(gt=0, le=1_000_000)]
    policy_digest: Digest

    @field_validator("budget_usd")
    @classmethod
    def finite_budget(cls, value: float) -> float:
        return _finite(value)


class UsageObservation(_Model):
    """Unknown usage is structurally null and can never be rendered as zero."""

    state: ValueState
    provider_usage_digest: Digest | None = None
    price_catalog_revision: Identifier | None = None
    input_tokens: Annotated[int, Field(ge=0)] | None = None
    output_tokens: Annotated[int, Field(ge=0)] | None = None
    cost_usd: Annotated[float, Field(ge=0)] | None = None

    @field_validator("cost_usd")
    @classmethod
    def finite_cost(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value)

    @model_validator(mode="after")
    def observed_or_null(self) -> UsageObservation:
        values = (self.provider_usage_digest, self.price_catalog_revision, self.input_tokens, self.output_tokens, self.cost_usd)
        if self.state == "unknown" and any(value is not None for value in values):
            raise ValueError("unknown usage must leave every value null")
        if self.state == "observed" and any(value is None for value in values):
            raise ValueError("observed usage requires provider usage, price revision, tokens, and cost")
        return self


class ReplayBranchOutcome(_Model):
    result_digest: Digest
    trace_digest: Digest
    evaluator_output_digest: Digest
    quality_score: Annotated[float, Field(ge=0, le=1)]
    latency_state: ValueState
    latency_ms: Annotated[int, Field(ge=0)] | None = None
    usage: UsageObservation
    fidelity_state: EvidenceState
    fidelity_level: FidelityLevel | None = None
    process_safety: ProcessSafety
    severe_failure_codes: list[Identifier] = Field(default_factory=list, max_length=64)

    @field_validator("quality_score")
    @classmethod
    def finite_score(cls, value: float) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def values_remain_unknown(self) -> ReplayBranchOutcome:
        if self.latency_state == "unknown" and self.latency_ms is not None:
            raise ValueError("unknown latency must be null, never zero")
        if self.latency_state == "observed" and self.latency_ms is None:
            raise ValueError("observed latency requires a value")
        if self.fidelity_state == "unknown" and self.fidelity_level is not None:
            raise ValueError("unknown fidelity must not carry a level")
        if self.fidelity_state != "unknown" and self.fidelity_level is None:
            raise ValueError("observed fidelity requires a level")
        if len(self.severe_failure_codes) != len(set(self.severe_failure_codes)):
            raise ValueError("severe failure codes must be unique")
        return self


class ReplayPair(_Model):
    pair_id: Identifier
    task_item_digest: Digest
    repetition: Annotated[int, Field(ge=1, le=512)]
    base: ReplayBranchOutcome
    candidate: ReplayBranchOutcome

    @model_validator(mode="after")
    def branches_differ(self) -> ReplayPair:
        if self.base.result_digest == self.candidate.result_digest:
            raise ValueError("base and candidate results must remain distinct")
        return self


class CounterfactualReplayRequest(_Model):
    schema_version: Literal["scaffold-arena.counterfactual-replay/1"] = "scaffold-arena.counterfactual-replay/1"
    mode: ReplayMode = "fixture"
    binding: ReplayBinding
    intervention: MechanismIntervention
    semantic_diff: SemanticMechanismDiff
    allocation: CohortAllocation
    analysis_plan: ReplayAnalysisPlan
    pairs: list[ReplayPair] = Field(min_length=1, max_length=512)
    live_authorization: LiveAuthorization | None = None

    @model_validator(mode="after")
    def paired_contract(self) -> CounterfactualReplayRequest:
        if self.semantic_diff.changed_mechanism_ids != [self.intervention.mechanism_id]:
            raise ValueError("semantic diff must name exactly the declared intervention")
        if len({pair.pair_id for pair in self.pairs}) != len(self.pairs) or len({pair.repetition for pair in self.pairs}) != len(self.pairs):
            raise ValueError("pair ids and repetitions must be unique")
        if any(pair.task_item_digest not in self.allocation.replay_item_digests for pair in self.pairs):
            raise ValueError("each pair must use a predeclared replay item")
        if len(self.pairs) > self.analysis_plan.planned_repetitions:
            raise ValueError("recorded pairs exceed predeclared repetitions")
        if self.mode == "live" and self.live_authorization is None:
            raise ValueError("live mode requires explicit credentials, budget, and policy attestation")
        if self.mode != "live" and self.live_authorization is not None:
            raise ValueError("live authorization is only valid in live mode")
        if self.mode == "fixture" and any(outcome.usage.state == "observed" for pair in self.pairs for outcome in (pair.base, pair.candidate)):
            raise ValueError("fixtures cannot claim provider-observed usage")
        return self


class EffectEstimate(_Model):
    metric: Literal["quality", "cost_usd", "latency_ms"]
    state: ValueState
    point_estimate: float | None = None
    ci95_low: float | None = None
    ci95_high: float | None = None
    base_mean: float | None = None
    candidate_mean: float | None = None
    paired_samples: Annotated[int, Field(ge=0)]
    reason: Text

    @model_validator(mode="after")
    def effect_integrity(self) -> EffectEstimate:
        values = (self.point_estimate, self.ci95_low, self.ci95_high, self.base_mean, self.candidate_mean)
        if self.state == "unknown" and any(value is not None for value in values):
            raise ValueError("unknown effects cannot become zeros")
        if self.state == "observed" and (self.point_estimate is None or self.base_mean is None or self.candidate_mean is None):
            raise ValueError("observed effects need point, base, and candidate values")
        return self


class MaturityAssessment(_Model):
    maturity: EvidenceMaturity
    state: EvidenceState
    reason: Text


class ConditionalMeasure(_Model):
    """Causal-family measures stay unestimated until their own assumptions bind."""

    measure: Literal[
        "intention_to_treat",
        "opportunity",
        "activation",
        "fidelity_failure",
        "treatment_on_the_treated",
    ]
    state: Literal["unknown", "ineligible"]
    value: None = None
    reason: Text


class ReplayPairReference(_Model):
    pair_id: Identifier
    task_item_digest: Digest
    base_result_digest: Digest
    candidate_result_digest: Digest
    base_trace_digest: Digest
    candidate_trace_digest: Digest
    base_usage_state: ValueState
    candidate_usage_state: ValueState


class CounterfactualReplayReport(_Model):
    schema_version: Literal["scaffold-arena.counterfactual-replay-report/1"]
    report_id: Identifier
    report_digest: Digest
    report_artifact_digest: Digest
    request_digest: Digest
    binding_digest: Digest
    mode: ReplayMode
    verdict: Verdict
    evidence_maturity: EvidenceMaturity
    maturity_ladder: list[MaturityAssessment]
    pair_count: Annotated[int, Field(ge=1)]
    planned_repetitions: Annotated[int, Field(ge=1)]
    pair_references: list[ReplayPairReference]
    intervention: MechanismIntervention
    semantic_diff: SemanticMechanismDiff
    effects: list[EffectEstimate]
    conditional_measures: list[ConditionalMeasure]
    new_severe_failures: list[Identifier]
    usage_state: ValueState
    fidelity_level: FidelityLevel | None = None
    process_safety: ProcessSafety
    claim_ceiling: Text
    limitations: list[Text] = Field(default_factory=list, max_length=64)
    provider_execution_started: Literal[False] = False
    execution_started: Literal[False] = False
    network_requested: Literal[False] = False
    idempotent_replay: bool = False

    @model_validator(mode="after")
    def all_conditional_measures_are_explicit(self) -> CounterfactualReplayReport:
        required = {
            "intention_to_treat", "opportunity", "activation", "fidelity_failure",
            "treatment_on_the_treated",
        }
        actual = [item.measure for item in self.conditional_measures]
        if set(actual) != required or len(actual) != len(required):
            raise ValueError("all conditional causal-family measures must remain explicit")
        return self


class SourceChange(_Model):
    """In-memory diff input; report serialization never includes this text."""

    path: Annotated[str, Field(min_length=1, max_length=256)]
    diff_text: Annotated[str, Field(min_length=1, max_length=32768)]

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value or ".." in value.split("/"):
            raise ValueError("paths must be normalized relative paths")
        return value


class HarnessCIPolicy(_Model):
    fail_on_new_severe_failures: bool = True
    max_quality_regression: Annotated[float, Field(ge=0, le=1)] = 0.0
    max_cost_increase_ratio: Annotated[float, Field(ge=0, le=100)] = 0.25
    max_latency_increase_ratio: Annotated[float, Field(ge=0, le=100)] = 0.25
    required_cohorts: list[Literal["development", "holdout"]] = Field(default_factory=lambda: ["development"])
    unknown_usage: Literal["hold", "fail"] = "hold"
    required_evidence_maturity: EvidenceMaturity = "paired_replay"
    minimum_paired_repetitions: Annotated[int, Field(ge=1, le=512)] = 2
    minimum_fidelity: FidelityLevel = "applied"
    require_process_safety: bool = True
    allow_fixture_evidence: bool = True

    @field_validator("max_quality_regression", "max_cost_increase_ratio", "max_latency_increase_ratio")
    @classmethod
    def finite_policy_values(cls, value: float) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def cohorts_unique(self) -> HarnessCIPolicy:
        if not self.required_cohorts or len(self.required_cohorts) != len(set(self.required_cohorts)):
            raise ValueError("required cohorts must be nonempty and unique")
        return self


class HarnessCIRequest(_Model):
    schema_version: Literal["scaffold-arena.harness-ci/1"] = "scaffold-arena.harness-ci/1"
    replay_report_digest: Digest
    base_source_digest: Digest
    candidate_source_digest: Digest
    source_changes: list[SourceChange] = Field(default_factory=list, max_length=64)
    policy: HarnessCIPolicy

    @model_validator(mode="after")
    def candidate_differs(self) -> HarnessCIRequest:
        if self.base_source_digest == self.candidate_source_digest:
            raise ValueError("base and candidate source digests must differ")
        return self


class HarnessCICheck(_Model):
    check_id: Identifier
    verdict: Verdict
    detail: Text


class SemanticDiffResult(_Model):
    affected_mechanisms: list[Identifier]
    recommended_packs: list[Identifier]
    classification_state: Literal["observed", "unknown", "multiple"]


class HarnessCIReport(_Model):
    schema_version: Literal["scaffold-arena.harness-ci-report/1"]
    report_id: Identifier
    report_digest: Digest
    report_artifact_digest: Digest
    replay_report_digest: Digest
    verdict: Verdict
    checks: list[HarnessCICheck]
    effects: list[EffectEstimate]
    severe_failures: list[Identifier]
    usage_state: ValueState
    fidelity_level: FidelityLevel | None = None
    evidence_maturity: EvidenceMaturity
    semantic_diff: SemanticDiffResult
    reproduction_command: Text
    step_summary: Annotated[str, Field(min_length=1, max_length=16384)]
    pr_comment_body: Annotated[str, Field(min_length=1, max_length=16384)]
    claim_ceiling: Text
    provider_execution_started: Literal[False] = False
    execution_started: Literal[False] = False
    network_requested: Literal[False] = False
    idempotent_replay: bool = False
