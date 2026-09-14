"""Pure, deterministic Analysis v1 report construction.

This module accepts only already-persisted, data-only records.  It neither
loads data nor fits models: a caller can safely invoke it after an API has
resolved immutable attempt records.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from math import isfinite
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .adequacy import AdequacyInput, AdequacyRequirements, assess_analysis_adequacy
from .decision import (
    CostStatus,
    ParetoProfile,
    ProfileConstraints,
    minimum_sufficient_profile,
    pareto_frontier,
)
from .research import ResearchAnalysisReport, fit_preregistered_logistic
from .statistics import (
    PairedBinaryObservation,
    PairedContinuousObservation,
    benjamini_hochberg,
    cluster_sign_flip_p_value,
    holm,
    paired_binary_risk_difference,
    paired_continuous_effect,
    task_cluster_bootstrap_ci,
)


class AnalysisModel(BaseModel):
    """Strict immutable JSON contract; coercion and unrecognised fields fail."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, allow_inf_nan=False
    )


class FactorLevel(AnalysisModel):
    factor_id: str = Field(min_length=1)
    level: str | int | bool

    @field_validator("level")
    @classmethod
    def valid_level(cls, value: str | int | bool) -> str | int | bool:
        if isinstance(value, str) and not value:
            raise ValueError("factor levels cannot be blank strings")
        return value


class RegisteredFactor(AnalysisModel):
    factor_id: str = Field(min_length=1)
    levels: tuple[str | int | bool, ...] = Field(min_length=2)

    @field_validator("levels")
    @classmethod
    def unique_levels(
        cls, value: tuple[str | int | bool, ...]
    ) -> tuple[str | int | bool, ...]:
        if len(set(value)) != len(value) or any(
            isinstance(item, str) and not item for item in value
        ):
            raise ValueError("registered factor levels must be non-empty and unique")
        return value


class ExternalFitterReceipt(AnalysisModel):
    """A supplied result, never a model constructed by this module."""

    receipt_id: str = Field(min_length=1)
    fitter: str = Field(min_length=1)
    fitter_version: str = Field(min_length=1)
    immutable: Literal[True] = True
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    result_ref: str = Field(min_length=1)


class AttemptRecord(AnalysisModel):
    attempt_id: str = Field(min_length=1)
    episode_id: str | None = None
    constituent_attempt_ids: tuple[str, ...] = ()
    experiment_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_cluster_id: str = Field(min_length=1)
    scaffold_id: str = Field(min_length=1)
    pair_id: str | None = None
    repeat_index: int = Field(ge=1)
    variant: Literal["clean", "stress"] = "clean"
    factor_levels: tuple[FactorLevel, ...] = ()
    success: bool
    continuous_outcomes: tuple[tuple[str, float], ...] = ()
    severe_failures: tuple[str, ...] = ()
    auditability: float = Field(ge=0.0, le=1.0)
    trace_complete: bool
    manipulation_pass: bool
    evaluator_independent: bool
    held_out: bool
    cost_status: CostStatus
    cost_usd: float | None = Field(default=None, ge=0.0)
    provider_usage_ref: str | None = None
    price_reference: str | None = None
    latency_seconds: float | None = Field(default=None, ge=0.0)
    excluded: bool = False
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def validate_record(self) -> AttemptRecord:
        constituents = self.constituent_attempt_ids or (self.attempt_id,)
        if len(set(constituents)) != len(constituents) or self.attempt_id not in constituents:
            raise ValueError("constituent attempt ids must be unique and include the final attempt")
        factor_ids = [item.factor_id for item in self.factor_levels]
        if len(set(factor_ids)) != len(factor_ids):
            raise ValueError("an attempt cannot contain duplicate factor assignments")
        names = [name for name, _ in self.continuous_outcomes]
        if len(set(names)) != len(names) or any(not name for name in names):
            raise ValueError("continuous outcome names must be non-empty and unique")
        if any(not isfinite(value) for _, value in self.continuous_outcomes):
            raise ValueError("continuous outcomes must be finite")
        if any(not failure for failure in self.severe_failures):
            raise ValueError("severe failure labels must be non-empty")
        reconciled = self.cost_status is CostStatus.RECONCILED
        if reconciled and (
            self.cost_usd is None
            or not self.provider_usage_ref
            or not self.price_reference
        ):
            raise ValueError(
                "RECONCILED cost requires amount, provider usage reference, and price reference"
            )
        if not reconciled and any(
            value is not None
            for value in (self.cost_usd, self.provider_usage_ref, self.price_reference)
        ):
            raise ValueError(
                "UNKNOWN cost must not carry a cost, usage reference, or price reference"
            )
        if self.excluded != (self.exclusion_reason is not None):
            raise ValueError(
                "excluded attempts require an exclusion_reason, and included attempts cannot carry one"
            )
        return self

    @property
    def factors(self) -> tuple[tuple[str, str | int | bool], ...]:
        return tuple(
            sorted((item.factor_id, item.level) for item in self.factor_levels)
        )

    def outcome(self, metric_id: str) -> float:
        for name, value in self.continuous_outcomes:
            if name == metric_id:
                return value
        raise ValueError(
            f"attempt {self.attempt_id} lacks continuous outcome {metric_id!r}"
        )


class MainEffectSpec(AnalysisModel):
    effect_id: str = Field(min_length=1)
    factor_id: str = Field(min_length=1)
    control_level: str | int | bool
    treatment_level: str | int | bool
    outcome: Literal["success", "continuous"] = "success"
    metric_id: str | None = None
    pairing_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_metric(self) -> MainEffectSpec:
        if self.control_level == self.treatment_level:
            raise ValueError("control and treatment levels must differ")
        if (self.outcome == "continuous") != (self.metric_id is not None):
            raise ValueError(
                "continuous effects require metric_id and binary success effects must not carry one"
            )
        return self


class InteractionSpec(AnalysisModel):
    interaction_id: str = Field(min_length=1)
    factor_a: str = Field(min_length=1)
    control_a: str | int | bool
    treatment_a: str | int | bool
    factor_b: str = Field(min_length=1)
    control_b: str | int | bool
    treatment_b: str | int | bool
    outcome: Literal["success", "continuous"] = "success"
    metric_id: str | None = None
    minimum_effective_pairs: int = Field(default=2, ge=2)
    minimum_clusters: int = Field(default=2, ge=2)

    @model_validator(mode="after")
    def validate_interaction(self) -> InteractionSpec:
        if self.factor_a == self.factor_b:
            raise ValueError("interaction factors must differ")
        if self.control_a == self.treatment_a or self.control_b == self.treatment_b:
            raise ValueError("interaction control and treatment levels must differ")
        if (self.outcome == "continuous") != (self.metric_id is not None):
            raise ValueError(
                "continuous interactions require metric_id and binary interactions must not carry one"
            )
        return self


class AnalysisGates(AnalysisModel):
    preregistered_design: bool
    # Retained for frozen-config compatibility only. This declaration is not
    # persisted cross-arm evidence and cannot establish claim eligibility.
    comparison_invariants_pass: bool
    minimum_manipulation_fidelity: float = Field(default=0.95, ge=0.0, le=1.0)
    minimum_trace_completeness: float = Field(default=0.95, ge=0.0, le=1.0)
    require_evaluator_independence: bool = True
    require_held_out_tasks: bool = True
    external_fitter_receipt: ExternalFitterReceipt | None = None


class AnalysisOptions(AnalysisModel):
    pass_k: int = Field(default=3, ge=2)
    bootstrap_resamples: int = Field(default=2_000, ge=1)
    bootstrap_seed: int = 0
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    minimum_clusters: int = Field(default=2, ge=2)
    primary_correction: Literal["holm"] = "holm"
    secondary_correction: Literal["benjamini-hochberg"] = "benjamini-hochberg"
    minimum_profile_constraints: ProfileConstraints | None = None


class AnalysisInput(AnalysisModel):
    schema_version: Literal["analysis-v1"] = "analysis-v1"
    experiment_id: str = Field(min_length=1)
    registered_factors: tuple[RegisteredFactor, ...] = ()
    primary_main_effects: tuple[MainEffectSpec, ...] = ()
    secondary_interactions: tuple[InteractionSpec, ...] = ()
    attempts: tuple[AttemptRecord, ...] = Field(min_length=1)
    gates: AnalysisGates
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)

    @model_validator(mode="after")
    def validate_input(self) -> AnalysisInput:
        identifiers = [item.attempt_id for item in self.attempts]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate attempt_id values are forbidden")
        if any(item.experiment_id != self.experiment_id for item in self.attempts):
            raise ValueError("cross-experiment contamination is forbidden")
        episode_ids = [item.episode_id or item.attempt_id for item in self.attempts]
        if len(set(episode_ids)) != len(episode_ids):
            raise ValueError("duplicate episode_id values are forbidden")
        analysis_units = [
            (item.task_id, item.scaffold_id, item.factors, item.variant, item.repeat_index)
            for item in self.attempts
        ]
        if len(set(analysis_units)) != len(analysis_units):
            raise ValueError("duplicate episode repetition/profile/factor units are forbidden")
        factor_ids = [factor.factor_id for factor in self.registered_factors]
        if len(set(factor_ids)) != len(factor_ids):
            raise ValueError("registered factor ids must be unique")
        registered = {
            factor.factor_id: set(factor.levels) for factor in self.registered_factors
        }
        for attempt in self.attempts:
            for factor_id, level in attempt.factors:
                if factor_id not in registered or level not in registered[factor_id]:
                    raise ValueError("attempt contains an unregistered factor level")
        main_ids = [item.effect_id for item in self.primary_main_effects]
        interaction_ids = [item.interaction_id for item in self.secondary_interactions]
        if len(set(main_ids)) != len(main_ids) or len(set(interaction_ids)) != len(
            interaction_ids
        ):
            raise ValueError("effect identifiers must be unique within their family")
        for spec in self.primary_main_effects:
            _validate_registered_levels(
                registered, spec.factor_id, spec.control_level, spec.treatment_level
            )
        for spec in self.secondary_interactions:
            _validate_registered_levels(
                registered, spec.factor_a, spec.control_a, spec.treatment_a
            )
            _validate_registered_levels(
                registered, spec.factor_b, spec.control_b, spec.treatment_b
            )
        return self


def _validate_registered_levels(
    registered: dict[str, set[str | int | bool]],
    factor: str,
    *levels: str | int | bool,
) -> None:
    if factor not in registered or any(
        level not in registered[factor] for level in levels
    ):
        raise ValueError("effect specification contains an unregistered factor level")


class ChartSeries(AnalysisModel):
    series_id: str
    numerator: float
    denominator: int
    exclusions: tuple[tuple[str, str], ...]
    attempt_ids: tuple[str, ...]
    constituent_attempt_ids: tuple[str, ...] = ()
    value: float | None


class EffectReport(AnalysisModel):
    effect_id: str
    kind: Literal["main", "interaction"]
    outcome: str
    estimate: float | None
    confidence_interval: tuple[float | None, float | None]
    confidence_interval_scope: Literal["marginal"] = "marginal"
    cluster_count: int
    effective_pairs: int
    status: Literal["ESTIMATED", "HOLD"]
    reason: str | None
    raw_p_value: float | None = None
    adjusted_p_value: float | None = None
    rejected_after_correction: bool | None = None
    control_attempt_ids: tuple[str, ...] = ()
    treatment_attempt_ids: tuple[str, ...] = ()
    series: ChartSeries


class ProfileReport(AnalysisModel):
    profile_id: str
    attempt_ids: tuple[str, ...]
    pass_at_1: ChartSeries
    pass_at_k: ChartSeries
    pass_power_k: ChartSeries
    severe_failure: ChartSeries
    auditability: ChartSeries
    latency_seconds: ChartSeries
    cost_status: CostStatus
    cost_usd: ChartSeries
    provider_usage_refs: tuple[str, ...]
    price_references: tuple[str, ...]


class AdequacyReport(AnalysisModel):
    claim_level: str
    reasons: tuple[str, ...]
    manipulation_fidelity: float
    trace_completeness: float
    evaluator_independence: float
    held_out_coverage: float
    mixed_effect_status: Literal["NOT_RUN"]
    external_fitter_receipt: ExternalFitterReceipt | None


class AnalysisReport(AnalysisModel):
    schema_version: Literal["analysis-report-v1"] = "analysis-report-v1"
    experiment_id: str
    included_attempt_ids: tuple[str, ...]
    exclusions: tuple[tuple[str, str], ...]
    severe_failures_before_composites: tuple[tuple[str, int], ...]
    profiles: tuple[ProfileReport, ...]
    clean_vs_stressed_tax: tuple[EffectReport, ...]
    main_effects: tuple[EffectReport, ...]
    secondary_interactions: tuple[EffectReport, ...]
    primary_correction: Literal["holm"] | None = None
    secondary_correction: str
    adequacy: AdequacyReport
    research: ResearchAnalysisReport
    pareto_profile_ids: tuple[str, ...]
    pareto_exclusions: tuple[tuple[str, str], ...]
    minimum_sufficient_profile_id: str | None
    minimum_sufficient_status: str | None
    trace_attribution: Literal["DIAGNOSTIC_ONLY"] = "DIAGNOSTIC_ONLY"
    trace_attribution_note: str = (
        "first divergence is diagnostic only and is never a causal estimate"
    )
    canonical_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def build_analysis_report(payload: AnalysisInput) -> AnalysisReport:
    """Build a stable JSON report from validated persisted attempts."""
    included = tuple(
        sorted(
            (item for item in payload.attempts if not item.excluded),
            key=lambda item: item.attempt_id,
        )
    )
    if not included:
        raise ValueError("all attempts are excluded; no analysis denominator remains")
    exclusions = tuple(
        sorted(
            (item.attempt_id, item.exclusion_reason or "excluded")
            for item in payload.attempts
            if item.excluded
        )
    )
    severe = _severe_summary(included)
    profiles = tuple(
        _profile_report(profile_id, records, payload.options.pass_k)
        for profile_id, records in _by_profile(included).items()
    )
    main = _main_effect_reports(
        payload.primary_main_effects, included, payload.options
    )
    interactions = _interaction_reports(
        payload.secondary_interactions, included, payload.options
    )
    stress_tax = _clean_vs_stressed_tax(included, payload.options)
    adequacy = _adequacy(payload, included)
    research = fit_preregistered_logistic(
        attempts=included,
        registered_factors=payload.registered_factors,
        interactions=payload.secondary_interactions,
        claim_eligible=adequacy.claim_level == "CONFIRMATORY_ANALYSIS_ELIGIBLE",
    )
    pareto_ids, pareto_exclusions, minimum_id, minimum_status = _profiles_decision(
        profiles, payload.options.minimum_profile_constraints
    )
    body: dict[str, Any] = {
        "schema_version": "analysis-report-v1",
        "experiment_id": payload.experiment_id,
        "included_attempt_ids": tuple(item.attempt_id for item in included),
        "exclusions": exclusions,
        "severe_failures_before_composites": severe,
        "profiles": profiles,
        "clean_vs_stressed_tax": stress_tax,
        "main_effects": main,
        "secondary_interactions": interactions,
        "primary_correction": payload.options.primary_correction,
        "secondary_correction": payload.options.secondary_correction,
        "adequacy": adequacy,
        "research": research,
        "pareto_profile_ids": pareto_ids,
        "pareto_exclusions": pareto_exclusions,
        "minimum_sufficient_profile_id": minimum_id,
        "minimum_sufficient_status": minimum_status,
        "trace_attribution": "DIAGNOSTIC_ONLY",
        "trace_attribution_note": "first divergence is diagnostic only and is never a causal estimate",
    }
    digest = _canonical_hash(body)
    return AnalysisReport(**body, canonical_hash=digest)


def _canonical_hash(value: Any) -> str:
    import json

    return sha256(
        json.dumps(
            value,
            default=_json_default,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _by_profile(
    records: tuple[AttemptRecord, ...],
) -> dict[str, tuple[AttemptRecord, ...]]:
    grouped: dict[str, list[AttemptRecord]] = defaultdict(list)
    for record in records:
        grouped[record.scaffold_id].append(record)
    return {
        key: tuple(sorted(value, key=lambda item: item.attempt_id))
        for key, value in sorted(grouped.items())
    }


def _series(
    series_id: str,
    values: list[float],
    records: tuple[AttemptRecord, ...],
    *,
    exclusions: tuple[tuple[str, str], ...] = (),
    attempt_ids: tuple[str, ...] | None = None,
) -> ChartSeries:
    ids = (
        attempt_ids
        if attempt_ids is not None
        else tuple(item.attempt_id for item in records)
    )
    denominator = len(values)
    return ChartSeries(
        series_id=series_id,
        numerator=sum(values),
        denominator=denominator,
        exclusions=exclusions,
        attempt_ids=ids,
        constituent_attempt_ids=tuple(
            attempt_id
            for item in records
            for attempt_id in (item.constituent_attempt_ids or (item.attempt_id,))
        ),
        value=(sum(values) / denominator if denominator else None),
    )


def _profile_report(
    profile_id: str, records: tuple[AttemptRecord, ...], k: int
) -> ProfileReport:
    groups: dict[tuple[str, tuple[tuple[str, str], ...], str], list[AttemptRecord]] = (
        defaultdict(list)
    )
    for record in records:
        groups[(record.task_id, record.factors, record.variant)].append(record)
    ordered_groups = [
        tuple(sorted(group, key=lambda item: item.repeat_index))
        for _, group in sorted(groups.items())
    ]
    complete = [group for group in ordered_groups if len(group) >= k]
    incomplete_ids = tuple(
        sorted(
            item.attempt_id
            for group in ordered_groups
            if len(group) < k
            for item in group
        )
    )
    group_attempt_ids = tuple(
        item.attempt_id for group in complete for item in group[:k]
    )
    group_exclusions = tuple(
        (item_id, f"fewer than {k} repeated attempts for pass@k/pass^k")
        for item_id in incomplete_ids
    )
    pass_at_k = _series(
        f"{profile_id}:pass_at_{k}",
        [float(any(item.success for item in group[:k])) for group in complete],
        tuple(item for group in complete for item in group[:k]),
        exclusions=group_exclusions,
        attempt_ids=group_attempt_ids,
    )
    pass_power = _series(
        f"{profile_id}:pass_power_{k}",
        [float(all(item.success for item in group[:k])) for group in complete],
        tuple(item for group in complete for item in group[:k]),
        exclusions=group_exclusions,
        attempt_ids=group_attempt_ids,
    )
    latency_records = tuple(
        item for item in records if item.latency_seconds is not None
    )
    latency_exclusions = tuple(
        (item.attempt_id, "latency unavailable")
        for item in records
        if item.latency_seconds is None
    )
    all_reconciled = all(item.cost_status is CostStatus.RECONCILED for item in records)
    cost_records = records if all_reconciled else ()
    cost_exclusions = (
        ()
        if all_reconciled
        else tuple(
            (item.attempt_id, "cost UNKNOWN or unreconciled") for item in records
        )
    )
    return ProfileReport(
        profile_id=profile_id,
        attempt_ids=tuple(item.attempt_id for item in records),
        pass_at_1=_series(
            f"{profile_id}:pass_at_1",
            [float(item.success) for item in records],
            records,
        ),
        pass_at_k=pass_at_k,
        pass_power_k=pass_power,
        severe_failure=_series(
            f"{profile_id}:severe_failure",
            [float(bool(item.severe_failures)) for item in records],
            records,
        ),
        auditability=_series(
            f"{profile_id}:auditability",
            [item.auditability for item in records],
            records,
        ),
        latency_seconds=_series(
            f"{profile_id}:latency_seconds",
            [
                item.latency_seconds
                for item in latency_records
                if item.latency_seconds is not None
            ],
            latency_records,
            exclusions=latency_exclusions,
        ),
        cost_status=CostStatus.RECONCILED if all_reconciled else CostStatus.UNKNOWN,
        cost_usd=_series(
            f"{profile_id}:cost_usd",
            [item.cost_usd for item in cost_records if item.cost_usd is not None],
            cost_records,
            exclusions=cost_exclusions,
        ),
        provider_usage_refs=tuple(
            sorted(
                item.provider_usage_ref
                for item in cost_records
                if item.provider_usage_ref
            )
        ),
        price_references=tuple(
            sorted(
                item.price_reference for item in cost_records if item.price_reference
            )
        ),
    )


def _severe_summary(records: tuple[AttemptRecord, ...]) -> tuple[tuple[str, int], ...]:
    count: dict[str, int] = defaultdict(int)
    for record in records:
        for failure in record.severe_failures:
            count[failure] += 1
    return tuple(sorted(count.items()))


def _pair_records(
    records: tuple[AttemptRecord, ...],
    factor_ids: tuple[str, ...],
    needed: set[tuple[str | int | bool, ...]],
) -> list[tuple[str, tuple[AttemptRecord, ...]]]:
    buckets: dict[tuple[Any, ...], list[AttemptRecord]] = defaultdict(list)
    for record in records:
        if record.pair_id is None:
            continue
        assignments = dict(record.factors)
        levels = tuple(assignments.get(factor) for factor in factor_ids)
        if None in levels or levels not in needed:
            continue
        remaining = tuple(
            (factor, level)
            for factor, level in record.factors
            if factor not in factor_ids
        )
        buckets[
            (
                record.pair_id,
                record.task_id,
                record.task_cluster_id,
                record.scaffold_id,
                record.variant,
                remaining,
            )
        ].append(record)
    result: list[tuple[str, tuple[AttemptRecord, ...]]] = []
    for key, group in sorted(buckets.items(), key=lambda item: str(item[0])):
        if len(group) != len(needed):
            raise ValueError("unpaired or duplicated records where pairing is required")
        levels = [
            tuple(dict(item.factors)[factor] for factor in factor_ids) for item in group
        ]
        if set(levels) != needed or len(set(levels)) != len(levels):
            raise ValueError(
                "unpaired or duplicated factor cells where pairing is required"
            )
        result.append((key[2], tuple(sorted(group, key=lambda item: item.attempt_id))))
    if not result:
        raise ValueError("no complete paired records for preregistered effect")
    return result


def _main_effect(
    spec: MainEffectSpec, records: tuple[AttemptRecord, ...], options: AnalysisOptions
) -> EffectReport:
    needed = {(spec.control_level,), (spec.treatment_level,)}
    pairs = _pair_records(records, (spec.factor_id,), needed)
    control: list[AttemptRecord] = []
    treatment: list[AttemptRecord] = []
    values: list[tuple[str, float]] = []
    for cluster, group in pairs:
        lookup = {dict(item.factors)[spec.factor_id]: item for item in group}
        c, t = lookup[spec.control_level], lookup[spec.treatment_level]
        control.append(c)
        treatment.append(t)
        if spec.outcome == "success":
            values.append((cluster, float(t.success) - float(c.success)))
        else:
            assert spec.metric_id is not None
            values.append(
                (cluster, t.outcome(spec.metric_id) - c.outcome(spec.metric_id))
            )
    bootstrap = task_cluster_bootstrap_ci(
        values,
        confidence_level=options.confidence_level,
        resamples=options.bootstrap_resamples,
        seed=options.bootstrap_seed,
        minimum_clusters=options.minimum_clusters,
    )
    if not bootstrap.adequate_clusters:
        raise ValueError(
            f"inadequate task clusters for preregistered main effect {spec.effect_id}: {bootstrap.adequacy_reason}"
        )
    sign_flip = cluster_sign_flip_p_value(
        values,
        permutations=options.bootstrap_resamples,
        seed=options.bootstrap_seed,
    )
    if spec.outcome == "success":
        estimate = paired_binary_risk_difference(
            [
                PairedBinaryObservation(
                    c.attempt_id, c.task_cluster_id, c.success, t.success
                )
                for c, t in zip(control, treatment, strict=True)
            ]
        ).risk_difference
    else:
        assert spec.metric_id is not None
        estimate = paired_continuous_effect(
            [
                PairedContinuousObservation(
                    c.attempt_id,
                    c.task_cluster_id,
                    c.outcome(spec.metric_id),
                    t.outcome(spec.metric_id),
                )
                for c, t in zip(control, treatment, strict=True)
            ]
        ).mean_difference
    series = _series(
        f"effect:{spec.effect_id}",
        [value for _, value in values],
        tuple(treatment),
        attempt_ids=tuple(item.attempt_id for item in (*control, *treatment)),
    )
    return EffectReport(
        effect_id=spec.effect_id,
        kind="main",
        outcome=spec.metric_id or "success",
        estimate=estimate,
        confidence_interval=(bootstrap.lower, bootstrap.upper),
        cluster_count=bootstrap.cluster_count,
        effective_pairs=len(pairs),
        status="ESTIMATED",
        reason=None,
        raw_p_value=sign_flip.p_value,
        adjusted_p_value=None,
        rejected_after_correction=None,
        control_attempt_ids=tuple(item.attempt_id for item in control),
        treatment_attempt_ids=tuple(item.attempt_id for item in treatment),
        series=series,
    )


def _main_effect_reports(
    specs: tuple[MainEffectSpec, ...],
    records: tuple[AttemptRecord, ...],
    options: AnalysisOptions,
) -> tuple[EffectReport, ...]:
    """Apply the registered familywise Holm correction to primary effects."""
    if not specs:
        return ()
    reports = [
        _main_effect(spec, records, options)
        for spec in sorted(specs, key=lambda item: item.effect_id)
    ]
    correction = holm(
        [
            report.raw_p_value
            for report in reports
            if report.raw_p_value is not None
        ]
    )
    for index, report in enumerate(reports):
        reports[index] = report.model_copy(
            update={
                "adjusted_p_value": correction.adjusted_p_values[index],
                "rejected_after_correction": correction.reject[index],
            }
        )
    return tuple(reports)


def _interaction_reports(
    specs: tuple[InteractionSpec, ...],
    records: tuple[AttemptRecord, ...],
    options: AnalysisOptions,
) -> tuple[EffectReport, ...]:
    if not specs:
        return ()
    ordered = tuple(sorted(specs, key=lambda item: item.interaction_id))
    reports = [_interaction(spec, records, options) for spec in ordered]
    estimated = [
        (index, report)
        for index, report in enumerate(reports)
        if report.raw_p_value is not None
    ]
    if estimated:
        correction = benjamini_hochberg(
            [
                report.raw_p_value
                for _, report in estimated
                if report.raw_p_value is not None
            ]
        )
        for position, (index, report) in enumerate(estimated):
            reports[index] = report.model_copy(
                update={
                    "adjusted_p_value": correction.adjusted_p_values[position],
                    "rejected_after_correction": correction.reject[position],
                }
            )
    return tuple(reports)


def _interaction(
    spec: InteractionSpec, records: tuple[AttemptRecord, ...], options: AnalysisOptions
) -> EffectReport:
    needed = {
        (spec.control_a, spec.control_b),
        (spec.treatment_a, spec.control_b),
        (spec.control_a, spec.treatment_b),
        (spec.treatment_a, spec.treatment_b),
    }
    pairs = _pair_records(records, (spec.factor_a, spec.factor_b), needed)
    values: list[tuple[str, float]] = []
    ids: list[AttemptRecord] = []
    for cluster, group in pairs:
        lookup = {
            tuple(
                dict(item.factors)[factor] for factor in (spec.factor_a, spec.factor_b)
            ): item
            for item in group
        }
        cc, tc, ct, tt = (
            lookup[(spec.control_a, spec.control_b)],
            lookup[(spec.treatment_a, spec.control_b)],
            lookup[(spec.control_a, spec.treatment_b)],
            lookup[(spec.treatment_a, spec.treatment_b)],
        )

        def value(item: AttemptRecord) -> float:
            return (
                float(item.success)
                if spec.outcome == "success"
                else item.outcome(spec.metric_id or "")
            )

        values.append((cluster, (value(tt) - value(ct)) - (value(tc) - value(cc))))
        ids.extend((cc, tc, ct, tt))
    clusters = len({cluster for cluster, _ in values})
    effective = len(values)
    gated = (
        effective >= spec.minimum_effective_pairs and clusters >= spec.minimum_clusters
    )
    bootstrap = task_cluster_bootstrap_ci(
        values,
        confidence_level=options.confidence_level,
        resamples=options.bootstrap_resamples,
        seed=options.bootstrap_seed,
        minimum_clusters=max(options.minimum_clusters, spec.minimum_clusters),
    )
    estimable = gated and bootstrap.adequate_clusters
    sign_flip = (
        cluster_sign_flip_p_value(
            values,
            permutations=options.bootstrap_resamples,
            seed=options.bootstrap_seed,
        )
        if estimable
        else None
    )
    reason = (
        None
        if estimable
        else f"HOLD: hierarchical interaction requires {spec.minimum_effective_pairs} complete four-cell pairs and {spec.minimum_clusters} clusters"
    )
    series = _series(
        f"interaction:{spec.interaction_id}",
        [item for _, item in values],
        tuple(ids),
        attempt_ids=tuple(item.attempt_id for item in ids),
    )
    return EffectReport(
        effect_id=spec.interaction_id,
        kind="interaction",
        outcome=spec.metric_id or "success",
        estimate=mean(value for _, value in values) if estimable else None,
        confidence_interval=(
            bootstrap.lower if estimable else None,
            bootstrap.upper if estimable else None,
        ),
        cluster_count=clusters,
        effective_pairs=effective,
        status="ESTIMATED" if estimable else "HOLD",
        reason=reason,
        raw_p_value=sign_flip.p_value if sign_flip else None,
        adjusted_p_value=None,
        rejected_after_correction=None,
        control_attempt_ids=tuple(
            item.attempt_id
            for item in ids
            if dict(item.factors).get(spec.factor_a) == spec.control_a
        ),
        treatment_attempt_ids=tuple(
            item.attempt_id
            for item in ids
            if dict(item.factors).get(spec.factor_a) == spec.treatment_a
        ),
        series=series,
    )


def _clean_vs_stressed_tax(
    records: tuple[AttemptRecord, ...], options: AnalysisOptions
) -> tuple[EffectReport, ...]:
    """Stress-minus-clean success difference, paired on the ordinary task episode.

    It is an ordinary-task tax, not a causal attribution.  Incomplete observed
    clean/stress pairs are rejected rather than silently removed.
    """
    by_profile: dict[str, list[AttemptRecord]] = defaultdict(list)
    for record in records:
        by_profile[record.scaffold_id].append(record)
    reports: list[EffectReport] = []
    for profile_id, profile_records in sorted(by_profile.items()):
        buckets: dict[tuple[Any, ...], list[AttemptRecord]] = defaultdict(list)
        for record in profile_records:
            if record.pair_id is not None:
                buckets[(record.pair_id, record.scaffold_id, record.factors)].append(
                    record
                )
        pairs: list[tuple[AttemptRecord, AttemptRecord]] = []
        for group in buckets.values():
            variants = {item.variant for item in group}
            if variants == {"clean", "stress"}:
                if len(group) != 2:
                    raise ValueError(
                        "duplicate clean/stress attempts in ordinary-task pairing"
                    )
                clean = next(item for item in group if item.variant == "clean")
                stress = next(item for item in group if item.variant == "stress")
                pairs.append((clean, stress))
            elif variants & {"clean", "stress"} and len(variants) > 1:
                raise ValueError("unpaired clean/stress ordinary-task records")
        if not pairs:
            empty = ChartSeries(
                series_id=f"{profile_id}:clean_vs_stressed_tax",
                numerator=0.0,
                denominator=0,
                exclusions=(),
                attempt_ids=(),
                value=None,
            )
            reports.append(
                EffectReport(
                    effect_id=f"{profile_id}:clean_vs_stressed_tax",
                    kind="main",
                    outcome="success",
                    estimate=None,
                    confidence_interval=(None, None),
                    cluster_count=0,
                    effective_pairs=0,
                    status="HOLD",
                    reason="HOLD: no complete clean/stress ordinary-task pairs",
                    series=empty,
                )
            )
            continue
        values = [
            (clean.task_cluster_id, float(stress.success) - float(clean.success))
            for clean, stress in pairs
        ]
        bootstrap = task_cluster_bootstrap_ci(
            values,
            confidence_level=options.confidence_level,
            resamples=options.bootstrap_resamples,
            seed=options.bootstrap_seed,
            minimum_clusters=options.minimum_clusters,
        )
        clean_ids = tuple(clean.attempt_id for clean, _ in pairs)
        stress_ids = tuple(stress.attempt_id for _, stress in pairs)
        reports.append(
            EffectReport(
                effect_id=f"{profile_id}:clean_vs_stressed_tax",
                kind="main",
                outcome="success",
                estimate=mean(value for _, value in values)
                if bootstrap.adequate_clusters
                else None,
                confidence_interval=(bootstrap.lower, bootstrap.upper),
                cluster_count=bootstrap.cluster_count,
                effective_pairs=len(pairs),
                status="ESTIMATED" if bootstrap.adequate_clusters else "HOLD",
                reason=bootstrap.adequacy_reason,
                control_attempt_ids=clean_ids,
                treatment_attempt_ids=stress_ids,
                series=_series(
                    f"{profile_id}:clean_vs_stressed_tax",
                    [value for _, value in values],
                    tuple(stress for _, stress in pairs),
                    attempt_ids=clean_ids + stress_ids,
                ),
            )
        )
    return tuple(reports)


def _adequacy(
    payload: AnalysisInput, records: tuple[AttemptRecord, ...]
) -> AdequacyReport:
    manipulation = mean(float(item.manipulation_pass) for item in records)
    trace = mean(float(item.trace_complete) for item in records)
    evaluator = mean(float(item.evaluator_independent) for item in records)
    held_out = mean(float(item.held_out) for item in records)
    control, treatment = _relevant_arm_counts(payload, records)
    requirements = AdequacyRequirements(
        minimum_clusters=max(2, payload.options.minimum_clusters),
        minimum_manipulation_fidelity=payload.gates.minimum_manipulation_fidelity,
        minimum_trace_completeness=payload.gates.minimum_trace_completeness,
    )
    result = assess_analysis_adequacy(
        AdequacyInput(
            len(records),
            len({item.task_cluster_id for item in records}),
            control,
            treatment,
            manipulation,
            trace,
            preregistered_design=payload.gates.preregistered_design,
            treatment_manipulation_fidelity_pass=manipulation
            >= payload.gates.minimum_manipulation_fidelity,
            # A caller-declared boolean is not derived cross-arm evidence.
            comparison_invariants_pass=False,
            evaluator_independence_pass=(
                evaluator == 1.0
                if payload.gates.require_evaluator_independence
                else True
            ),
            sealed_or_held_out_tasks_pass=(
                held_out == 1.0 if payload.gates.require_held_out_tasks else True
            ),
            external_fitted_model_result=(
                payload.gates.external_fitter_receipt.result_ref
                if payload.gates.external_fitter_receipt
                else None
            ),
        ),
        requirements,
    )
    return AdequacyReport(
        claim_level=result.claim_level.value,
        reasons=result.reasons,
        manipulation_fidelity=manipulation,
        trace_completeness=trace,
        evaluator_independence=evaluator,
        held_out_coverage=held_out,
        mixed_effect_status=result.mixed_effect_status.value,
        external_fitter_receipt=None,
    )


def _relevant_arm_counts(
    payload: AnalysisInput, records: tuple[AttemptRecord, ...]
) -> tuple[int, int]:
    """Use a preregistered contrast, never a scaffold-name proxy, for balance."""
    if payload.primary_main_effects:
        counts: list[tuple[int, int]] = []
        for spec in payload.primary_main_effects:
            levels = [dict(item.factors).get(spec.factor_id) for item in records]
            counts.append(
                (levels.count(spec.control_level), levels.count(spec.treatment_level))
            )
        return min(left for left, _ in counts), min(right for _, right in counts)
    if payload.secondary_interactions:
        counts = []
        for spec in payload.secondary_interactions:
            levels = [
                (
                    dict(item.factors).get(spec.factor_a),
                    dict(item.factors).get(spec.factor_b),
                )
                for item in records
            ]
            control = sum(
                value
                in {
                    (spec.control_a, spec.control_b),
                    (spec.control_a, spec.treatment_b),
                }
                for value in levels
            )
            treatment = sum(
                value
                in {
                    (spec.treatment_a, spec.control_b),
                    (spec.treatment_a, spec.treatment_b),
                }
                for value in levels
            )
            counts.append((control, treatment))
        return min(left for left, _ in counts), min(right for _, right in counts)
    return 0, 0


def _profiles_decision(
    profiles: tuple[ProfileReport, ...], constraints: ProfileConstraints | None
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...], str | None, str | None]:
    candidates: list[ParetoProfile] = []
    for profile in profiles:
        if (
            profile.cost_status is CostStatus.RECONCILED
            and profile.cost_usd.value is not None
            and profile.latency_seconds.value is not None
        ):
            candidates.append(
                ParetoProfile(
                    profile.profile_id,
                    profile.pass_at_1.value or 0.0,
                    profile.auditability.value or 0.0,
                    profile.severe_failure.value or 0.0,
                    CostStatus.RECONCILED,
                    profile.cost_usd.value,
                    profile.latency_seconds.value,
                    profile.provider_usage_refs[0],
                    profile.price_references[0],
                )
            )
    unknown = tuple(
        (
            profile.profile_id,
            "excluded: cost is UNKNOWN or not reconciled from provider usage and price",
        )
        for profile in profiles
        if profile.cost_status is CostStatus.UNKNOWN
    )
    if not candidates:
        return (), unknown, None, "HOLD"
    frontier = pareto_frontier(tuple(candidates))
    if constraints is None:
        return (
            tuple(item.profile_id for item in frontier.frontier),
            unknown + frontier.excluded,
            None,
            None,
        )
    selected = minimum_sufficient_profile(tuple(candidates), constraints)
    return (
        tuple(item.profile_id for item in frontier.frontier),
        unknown + frontier.excluded,
        selected.profile.profile_id if selected.profile else None,
        selected.status.value,
    )


# Deliberately friendly aliases for the eventual API boundary.
AnalysisRequest = AnalysisInput
create_analysis_report = build_analysis_report
