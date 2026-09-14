"""Finite-sample descriptive and paired-effect estimators.

All estimates are empirical over the supplied observations; no function here
turns fixture output into a population or causal claim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import product
from math import isfinite
from random import Random
from statistics import mean


@dataclass(frozen=True)
class RateEstimate:
    successes: int
    trials: int
    estimate: float
    definition: str


def _validate_groups(attempt_groups: Sequence[Sequence[bool]], k: int) -> None:
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")
    if not attempt_groups:
        raise ValueError("at least one attempt group is required")
    for group in attempt_groups:
        if len(group) < k:
            raise ValueError("each attempt group must contain at least k attempts")
        if any(type(success) is not bool for success in group[:k]):
            raise ValueError("attempt outcomes must be bool")


def _rate(indicators: Sequence[bool], definition: str) -> RateEstimate:
    successes = sum(indicators)
    return RateEstimate(successes=successes, trials=len(indicators), estimate=successes / len(indicators), definition=definition)


def pass_at_1(attempt_groups: Sequence[Sequence[bool]]) -> RateEstimate:
    """Empirical success rate of the first attempt in every supplied group."""
    _validate_groups(attempt_groups, 1)
    return _rate([group[0] for group in attempt_groups], "mean(first attempt succeeds) across supplied groups")


def pass_at_k(attempt_groups: Sequence[Sequence[bool]], k: int) -> RateEstimate:
    """Empirical probability that at least one of a group's first k attempts succeeds."""
    _validate_groups(attempt_groups, k)
    return _rate([any(group[:k]) for group in attempt_groups], f"mean(any of first {k} attempts succeeds) across supplied groups")


def pass_power_k(attempt_groups: Sequence[Sequence[bool]], k: int) -> RateEstimate:
    """Empirical pass^k: all of a group's first k repeated attempts succeed."""
    _validate_groups(attempt_groups, k)
    return _rate([all(group[:k]) for group in attempt_groups], f"mean(all first {k} attempts succeed) across supplied groups")


pass_all_k = pass_power_k


@dataclass(frozen=True)
class PairedBinaryObservation:
    pair_id: str
    cluster_id: str
    control_success: bool
    treatment_success: bool

    def __post_init__(self) -> None:
        if not self.pair_id or not self.cluster_id:
            raise ValueError("pair_id and cluster_id are required")
        if type(self.control_success) is not bool or type(self.treatment_success) is not bool:
            raise ValueError("paired binary outcomes must be bool")


@dataclass(frozen=True)
class PairedBinaryEffect:
    pairs: int
    treatment_success_rate: float
    control_success_rate: float
    risk_difference: float
    discordant_treatment_only: int
    discordant_control_only: int


def paired_binary_risk_difference(observations: Sequence[PairedBinaryObservation]) -> PairedBinaryEffect:
    if not observations:
        raise ValueError("at least one paired observation is required")
    if len({item.pair_id for item in observations}) != len(observations):
        raise ValueError("pair_id values must be unique")
    treatment = [item.treatment_success for item in observations]
    control = [item.control_success for item in observations]
    return PairedBinaryEffect(
        pairs=len(observations),
        treatment_success_rate=mean(treatment),
        control_success_rate=mean(control),
        risk_difference=mean(float(t) - float(c) for t, c in zip(treatment, control, strict=True)),
        discordant_treatment_only=sum(t and not c for t, c in zip(treatment, control, strict=True)),
        discordant_control_only=sum(c and not t for t, c in zip(treatment, control, strict=True)),
    )


@dataclass(frozen=True)
class PairedContinuousObservation:
    pair_id: str
    cluster_id: str
    control_value: float
    treatment_value: float

    def __post_init__(self) -> None:
        if not self.pair_id or not self.cluster_id:
            raise ValueError("pair_id and cluster_id are required")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) for value in (self.control_value, self.treatment_value)):
            raise ValueError("continuous values must be finite numbers")


@dataclass(frozen=True)
class PairedContinuousEffect:
    pairs: int
    treatment_mean: float
    control_mean: float
    mean_difference: float


def paired_continuous_effect(observations: Sequence[PairedContinuousObservation]) -> PairedContinuousEffect:
    if not observations:
        raise ValueError("at least one paired observation is required")
    if len({item.pair_id for item in observations}) != len(observations):
        raise ValueError("pair_id values must be unique")
    treatment = [float(item.treatment_value) for item in observations]
    control = [float(item.control_value) for item in observations]
    return PairedContinuousEffect(len(observations), mean(treatment), mean(control), mean(t - c for t, c in zip(treatment, control, strict=True)))


@dataclass(frozen=True)
class BootstrapCI:
    estimate: float
    lower: float | None
    upper: float | None
    confidence_level: float
    resamples: int
    seed: int
    cluster_count: int
    adequate_clusters: bool
    adequacy_reason: str | None


def task_cluster_bootstrap_ci(
    values: Sequence[tuple[str, float]], *, confidence_level: float = 0.95, resamples: int = 2_000, seed: int = 0, minimum_clusters: int = 2,
) -> BootstrapCI:
    """Percentile CI resampling task clusters, retaining all values per selected cluster."""
    if not values:
        raise ValueError("at least one clustered value is required")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one")
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an integer")
    if not isinstance(minimum_clusters, int) or minimum_clusters < 2:
        raise ValueError("minimum_clusters must be at least two")
    clusters: dict[str, list[float]] = {}
    for cluster, value in values:
        if not cluster or not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
            raise ValueError("cluster identifiers and finite numeric values are required")
        clusters.setdefault(cluster, []).append(float(value))
    names = tuple(sorted(clusters))
    estimate = mean(value for _, value in values)
    if len(names) < minimum_clusters:
        return BootstrapCI(estimate, None, None, confidence_level, resamples, seed, len(names), False, f"requires at least {minimum_clusters} task clusters")
    rng = Random(seed)
    draws: list[float] = []
    for _ in range(resamples):
        selected = [names[rng.randrange(len(names))] for _ in names]
        sampled = [value for cluster in selected for value in clusters[cluster]]
        draws.append(mean(sampled))
    draws.sort()
    alpha = (1 - confidence_level) / 2
    lower = draws[max(0, int(alpha * resamples))]
    upper = draws[min(resamples - 1, int((1 - alpha) * resamples + 0.999999) - 1)]
    return BootstrapCI(estimate, lower, upper, confidence_level, resamples, seed, len(names), True, None)


@dataclass(frozen=True)
class CorrectionResult:
    adjusted_p_values: tuple[float, ...]
    reject: tuple[bool, ...]
    method: str
    alpha: float


@dataclass(frozen=True)
class ClusterSignFlipResult:
    observed_mean: float
    p_value: float
    cluster_count: int
    draws: int
    method: str
    seed: int


def cluster_sign_flip_p_value(
    values: Sequence[tuple[str, float]], *, permutations: int = 2_000, seed: int = 0,
) -> ClusterSignFlipResult:
    """Two-sided randomization test that flips whole task clusters together.

    Exact enumeration is used through sixteen clusters. Larger samples use a
    deterministic Monte Carlo approximation with the supplied seed. Values
    within a cluster always receive the same sign, preserving dependence.
    """
    if not values:
        raise ValueError("at least one clustered value is required")
    if not isinstance(permutations, int) or isinstance(permutations, bool) or permutations < 1:
        raise ValueError("permutations must be a positive integer")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an integer")
    clusters: dict[str, list[float]] = {}
    for cluster, value in values:
        if not cluster or not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
            raise ValueError("cluster identifiers and finite numeric values are required")
        clusters.setdefault(cluster, []).append(float(value))
    names = tuple(sorted(clusters))
    flattened = tuple(value for name in names for value in clusters[name])
    observed = abs(mean(flattened))

    def statistic(signs: Sequence[int]) -> float:
        signed = [sign * value for sign, name in zip(signs, names, strict=True) for value in clusters[name]]
        return abs(mean(signed))

    tolerance = 1e-15
    if len(names) <= 16:
        all_signs = product((-1, 1), repeat=len(names))
        tested = 0
        extreme = 0
        for signs in all_signs:
            tested += 1
            extreme += statistic(signs) + tolerance >= observed
        return ClusterSignFlipResult(mean(flattened), extreme / tested, len(names), tested, "exact-cluster-sign-flip", seed)

    rng = Random(seed)
    extreme = 0
    for _ in range(permutations):
        signs = tuple(1 if rng.randrange(2) else -1 for _ in names)
        extreme += statistic(signs) + tolerance >= observed
    return ClusterSignFlipResult(
        mean(flattened), (extreme + 1) / (permutations + 1), len(names), permutations,
        "monte-carlo-cluster-sign-flip", seed,
    )


def _validate_p_values(p_values: Sequence[float], alpha: float) -> None:
    if not p_values:
        raise ValueError("at least one p-value is required")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between zero and one")
    if any(not isinstance(p, (int, float)) or isinstance(p, bool) or not isfinite(p) or not 0 <= p <= 1 for p in p_values):
        raise ValueError("p-values must be finite numbers in [0, 1]")


def benjamini_hochberg(p_values: Sequence[float], *, alpha: float = 0.05) -> CorrectionResult:
    _validate_p_values(p_values, alpha)
    indexed = sorted(enumerate(map(float, p_values)), key=lambda item: item[1])
    total = len(indexed)
    adjusted = [0.0] * total
    running = 1.0
    for position in range(total - 1, -1, -1):
        original, value = indexed[position]
        running = min(running, value * total / (position + 1))
        adjusted[original] = running
    return CorrectionResult(tuple(adjusted), tuple(value <= alpha for value in adjusted), "benjamini-hochberg", alpha)


def holm(p_values: Sequence[float], *, alpha: float = 0.05) -> CorrectionResult:
    _validate_p_values(p_values, alpha)
    indexed = sorted(enumerate(map(float, p_values)), key=lambda item: item[1])
    total = len(indexed)
    adjusted = [0.0] * total
    running = 0.0
    for position, (original, value) in enumerate(indexed):
        running = max(running, min(1.0, value * (total - position)))
        adjusted[original] = running
    return CorrectionResult(tuple(adjusted), tuple(value <= alpha for value in adjusted), "holm", alpha)
