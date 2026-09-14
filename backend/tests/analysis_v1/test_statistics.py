import pytest

from analysis_v1.statistics import (
    PairedBinaryObservation,
    PairedContinuousObservation,
    benjamini_hochberg,
    cluster_sign_flip_p_value,
    holm,
    paired_binary_risk_difference,
    paired_continuous_effect,
    pass_all_k,
    pass_at_1,
    pass_at_k,
    pass_power_k,
    task_cluster_bootstrap_ci,
)


def test_pass_metrics_cover_none_one_and_all_successes():
    attempts = ((False, False, False), (True, False, False), (True, True, True))
    assert pass_at_1(attempts).estimate == pytest.approx(2 / 3)
    assert pass_at_k(attempts, 2).estimate == pytest.approx(2 / 3)
    assert pass_all_k(attempts, 2).estimate == pytest.approx(1 / 3)
    assert pass_power_k(attempts, 2) == pass_all_k(attempts, 2)
    assert pass_at_k(((False, False),), 2).successes == 0
    assert pass_all_k(((True, True),), 2).successes == 1


def test_pass_metrics_reject_underfilled_or_invalid_groups():
    with pytest.raises(ValueError):
        pass_at_k(((True,),), 2)
    with pytest.raises(ValueError):
        pass_at_1(())
    with pytest.raises(ValueError):
        pass_all_k(((1,),), 1)  # type: ignore[arg-type]


def test_paired_effects_recover_known_synthetic_effects():
    binary = [PairedBinaryObservation(f"p{i}", "task-a" if i < 2 else "task-b", False, True) for i in range(4)]
    effect = paired_binary_risk_difference(binary)
    assert effect.risk_difference == 1.0
    assert effect.discordant_treatment_only == 4
    continuous = [PairedContinuousObservation(f"c{i}", "task-a" if i < 2 else "task-b", 2.0, 5.0) for i in range(4)]
    assert paired_continuous_effect(continuous).mean_difference == 3.0


def test_cluster_bootstrap_is_seeded_and_reports_cluster_adequacy():
    values = (("large", 1.0), ("large", 1.0), ("large", 1.0), ("small", 0.0))
    first = task_cluster_bootstrap_ci(values, seed=17, resamples=200)
    second = task_cluster_bootstrap_ci(values, seed=17, resamples=200)
    assert first == second
    assert first.cluster_count == 2
    assert first.adequate_clusters is True
    assert first.lower is not None and first.upper is not None
    insufficient = task_cluster_bootstrap_ci((("only", 1.0),), seed=17)
    assert insufficient.adequate_clusters is False
    assert insufficient.lower is None


def test_multiplicity_returns_original_order_adjusted_values_and_flags():
    values = (0.04, 0.001, 0.03, 0.2)
    bh = benjamini_hochberg(values)
    holm_result = holm(values)
    assert bh.adjusted_p_values == pytest.approx((0.0533333333, 0.004, 0.0533333333, 0.2))
    assert bh.reject == (False, True, False, False)
    assert holm_result.adjusted_p_values == pytest.approx((0.09, 0.004, 0.09, 0.2))
    assert holm_result.reject == (False, True, False, False)


def test_cluster_sign_flip_is_derived_exact_and_seeded_without_splitting_clusters():
    exact = cluster_sign_flip_p_value((("a", 1.0), ("a", 1.0), ("b", 1.0)))
    assert exact.observed_mean == 1.0
    assert exact.p_value == pytest.approx(0.5)
    assert exact.draws == 4
    assert exact.method == "exact-cluster-sign-flip"
    values = tuple((f"cluster-{index}", 1.0) for index in range(17))
    first = cluster_sign_flip_p_value(values, permutations=100, seed=9)
    second = cluster_sign_flip_p_value(values, permutations=100, seed=9)
    assert first == second
    assert first.method == "monte-carlo-cluster-sign-flip"


def test_cluster_sign_flip_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        cluster_sign_flip_p_value(())
    with pytest.raises(ValueError):
        cluster_sign_flip_p_value((("", 1.0),))
    with pytest.raises(ValueError):
        cluster_sign_flip_p_value((("a", float("nan")),))
