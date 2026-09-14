"""Eligibility, failure, and profile-selection rules without hidden tradeoffs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class CostStatus(StrEnum):
    RECONCILED = "reconciled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OutcomeMeasurement:
    outcome_id: str
    success: bool
    severe_failures: tuple[str, ...]
    auditability: float
    cost_status: CostStatus
    cost_usd: float | None
    latency_seconds: float | None
    provider_usage_ref: str | None = None
    price_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.outcome_id or type(self.success) is not bool:
            raise ValueError("outcome_id and bool success are required")
        if not 0 <= self.auditability <= 1 or not isfinite(self.auditability):
            raise ValueError("auditability must be finite and in [0, 1]")
        if not isinstance(self.cost_status, CostStatus):
            raise TypeError("cost_status must be RECONCILED or UNKNOWN")
        reconciled = self.cost_status is CostStatus.RECONCILED
        if reconciled and (self.cost_usd is None or not isfinite(self.cost_usd) or self.cost_usd < 0):
            raise ValueError("reconciled cost requires a non-negative finite cost_usd")
        if reconciled and (not self.provider_usage_ref or not self.price_reference):
            raise ValueError("reconciled cost requires provider usage and price references")
        if not reconciled and any(value is not None for value in (self.cost_usd, self.provider_usage_ref, self.price_reference)):
            raise ValueError("UNKNOWN cost must not carry estimated cost or reconciliation references")
        if self.latency_seconds is not None and (not isfinite(self.latency_seconds) or self.latency_seconds < 0):
            raise ValueError("latency_seconds must be non-negative when present")


@dataclass(frozen=True)
class SevereFailureSummary:
    outcomes: int
    affected_outcomes: int
    affected_rate: float
    total_events: int
    by_rule: tuple[tuple[str, int], ...]


def summarize_severe_failures(outcomes: Sequence[OutcomeMeasurement]) -> SevereFailureSummary:
    if not outcomes:
        raise ValueError("at least one outcome is required")
    counts: dict[str, int] = {}
    for outcome in outcomes:
        for failure in outcome.severe_failures:
            if not failure:
                raise ValueError("severe failure labels must be non-empty")
            counts[failure] = counts.get(failure, 0) + 1
    affected = sum(bool(outcome.severe_failures) for outcome in outcomes)
    return SevereFailureSummary(len(outcomes), affected, affected / len(outcomes), sum(counts.values()), tuple(sorted(counts.items())))


@dataclass(frozen=True)
class EligibilityDecision:
    composite_score: float | None
    configured_gates: tuple[tuple[str, bool], ...]
    failed_gates: tuple[str, ...]
    eligible: bool
    reason: str


def evaluate_eligibility(composite_score: float | None, hard_gates: dict[str, bool]) -> EligibilityDecision:
    if composite_score is not None and (not isfinite(composite_score) or not 0 <= composite_score <= 1):
        raise ValueError("composite_score must be in [0, 1] when supplied")
    if any(not name or type(passed) is not bool for name, passed in hard_gates.items()):
        raise ValueError("hard gates require non-empty names and bool values")
    gates = tuple(sorted(hard_gates.items()))
    failed = tuple(name for name, passed in gates if not passed)
    if failed:
        return EligibilityDecision(composite_score, gates, failed, False, "ineligible: configured hard gate failed")
    return EligibilityDecision(composite_score, gates, (), True, "eligible: all configured hard gates passed")


@dataclass(frozen=True)
class ParetoProfile:
    profile_id: str
    success_rate: float
    auditability: float
    severe_failure_rate: float
    cost_status: CostStatus
    cost_usd: float | None
    latency_seconds: float | None
    provider_usage_ref: str | None = None
    price_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id is required")
        for value, name in ((self.success_rate, "success_rate"), (self.auditability, "auditability"), (self.severe_failure_rate, "severe_failure_rate")):
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        if not isinstance(self.cost_status, CostStatus):
            raise TypeError("cost_status must be RECONCILED or UNKNOWN")
        reconciled = self.cost_status is CostStatus.RECONCILED
        if reconciled and (self.cost_usd is None or not isfinite(self.cost_usd) or self.cost_usd < 0):
            raise ValueError("reconciled cost requires cost_usd")
        if reconciled and (not self.provider_usage_ref or not self.price_reference):
            raise ValueError("reconciled cost requires provider usage and price references")
        if not reconciled and any(value is not None for value in (self.cost_usd, self.provider_usage_ref, self.price_reference)):
            raise ValueError("UNKNOWN cost must not carry estimated cost or reconciliation references")
        if self.latency_seconds is None or not isfinite(self.latency_seconds) or self.latency_seconds < 0:
            raise ValueError("latency_seconds must be a non-negative finite value")


@dataclass(frozen=True)
class ParetoResult:
    frontier: tuple[ParetoProfile, ...]
    excluded: tuple[tuple[str, str], ...]


def _dominates(left: ParetoProfile, right: ParetoProfile) -> bool:
    assert left.cost_usd is not None and right.cost_usd is not None
    no_worse = (
        left.success_rate >= right.success_rate and left.auditability >= right.auditability
        and left.severe_failure_rate <= right.severe_failure_rate and left.cost_usd <= right.cost_usd
        and left.latency_seconds <= right.latency_seconds
    )
    strictly_better = (
        left.success_rate > right.success_rate or left.auditability > right.auditability
        or left.severe_failure_rate < right.severe_failure_rate or left.cost_usd < right.cost_usd
        or left.latency_seconds < right.latency_seconds
    )
    return no_worse and strictly_better


def pareto_frontier(profiles: Sequence[ParetoProfile]) -> ParetoResult:
    if not profiles:
        raise ValueError("at least one profile is required")
    if len({profile.profile_id for profile in profiles}) != len(profiles):
        raise ValueError("profile_id values must be unique")
    reconciled = [profile for profile in profiles if profile.cost_status is CostStatus.RECONCILED]
    excluded = tuple((profile.profile_id, "excluded: cost is UNKNOWN or not reconciled from provider usage and price") for profile in profiles if profile.cost_status is CostStatus.UNKNOWN)
    frontier = tuple(profile for profile in reconciled if not any(other.profile_id != profile.profile_id and _dominates(other, profile) for other in reconciled))
    return ParetoResult(frontier, excluded)


class ProfileStatus(StrEnum):
    MATCH = "MATCH"
    HOLD = "HOLD"


@dataclass(frozen=True)
class ProfileConstraints:
    max_severe_failure_rate: float
    max_cost_usd: float
    max_latency_seconds: float
    min_success_rate: float
    min_auditability: float = 0.0

    def __post_init__(self) -> None:
        for value, name in ((self.max_severe_failure_rate, "max_severe_failure_rate"), (self.min_success_rate, "min_success_rate"), (self.min_auditability, "min_auditability")):
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and in [0, 1]")
        for value, name in ((self.max_cost_usd, "max_cost_usd"), (self.max_latency_seconds, "max_latency_seconds")):
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be non-negative and finite")


@dataclass(frozen=True)
class MinimumSufficientResult:
    status: ProfileStatus
    profile: ParetoProfile | None
    reason: str


def minimum_sufficient_profile(profiles: Sequence[ParetoProfile], constraints: ProfileConstraints) -> MinimumSufficientResult:
    candidates = [
        profile for profile in profiles
        if profile.cost_status is CostStatus.RECONCILED and profile.cost_usd is not None
        and profile.severe_failure_rate <= constraints.max_severe_failure_rate
        and profile.cost_usd <= constraints.max_cost_usd and profile.latency_seconds <= constraints.max_latency_seconds
        and profile.success_rate >= constraints.min_success_rate and profile.auditability >= constraints.min_auditability
    ]
    if not candidates:
        return MinimumSufficientResult(ProfileStatus.HOLD, None, "HOLD: no profile satisfies every risk, cost, latency, reliability, and auditability constraint")
    chosen = min(candidates, key=lambda profile: (profile.cost_usd, profile.latency_seconds, -profile.success_rate, -profile.auditability, profile.profile_id))
    return MinimumSufficientResult(ProfileStatus.MATCH, chosen, "MATCH: selected lowest-cost profile satisfying every constraint")
