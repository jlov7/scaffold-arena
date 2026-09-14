from analysis_v1.decision import (
    CostStatus,
    OutcomeMeasurement,
    ParetoProfile,
    ProfileConstraints,
    ProfileStatus,
    evaluate_eligibility,
    minimum_sufficient_profile,
    pareto_frontier,
    summarize_severe_failures,
)


def profile(identifier: str, *, success: float = 0.9, audit: float = 0.9, severe: float = 0.0, cost: float | None = 1.0, latency: float = 1.0) -> ParetoProfile:
    if cost is None:
        return ParetoProfile(identifier, success, audit, severe, CostStatus.UNKNOWN, None, latency)
    return ParetoProfile(identifier, success, audit, severe, CostStatus.RECONCILED, cost, latency, "provider-usage", "price-ledger")


def test_hard_gate_dominates_composite_and_severe_summary_is_separate():
    decision = evaluate_eligibility(1.0, {"no_severe_failure": False, "trace_complete": True})
    assert decision.eligible is False
    assert decision.failed_gates == ("no_severe_failure",)
    summary = summarize_severe_failures((
        OutcomeMeasurement("a", True, ("unsafe",), 1.0, CostStatus.RECONCILED, 0.1, 1.0, "usage-a", "price-a"),
        OutcomeMeasurement("b", True, (), 1.0, CostStatus.RECONCILED, 0.1, 1.0, "usage-b", "price-b"),
    ))
    assert summary.affected_rate == 0.5
    assert summary.by_rule == (("unsafe", 1),)


def test_pareto_keeps_ties_and_excludes_unknown_cost_without_zero_imputation():
    tied_a = profile("tied-a")
    tied_b = profile("tied-b")
    dominated = profile("dominated", success=0.8, audit=0.8, severe=0.1, cost=2.0, latency=2.0)
    unknown = profile("unknown", cost=None)
    result = pareto_frontier((tied_a, tied_b, dominated, unknown))
    assert result.frontier == (tied_a, tied_b)
    assert result.excluded == (("unknown", "excluded: cost is UNKNOWN or not reconciled from provider usage and price"),)


def test_estimated_or_known_but_unreconciled_cost_cannot_enter_pareto():
    with pytest.raises(TypeError, match="RECONCILED or UNKNOWN"):
        ParetoProfile("estimated", 1.0, 1.0, 0.0, "known", 0.01, 0.1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="provider usage and price"):
        ParetoProfile("unreconciled", 1.0, 1.0, 0.0, CostStatus.RECONCILED, 0.01, 0.1)


def test_minimum_sufficient_profile_returns_hold_when_no_profile_matches():
    constraints = ProfileConstraints(0.0, 0.5, 1.0, 0.95)
    result = minimum_sufficient_profile((profile("near", success=0.94, cost=0.5),), constraints)
    assert result.status is ProfileStatus.HOLD
    assert result.profile is None
import pytest
