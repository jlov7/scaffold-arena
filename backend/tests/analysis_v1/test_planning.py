from __future__ import annotations

import importlib

from protocol_v1 import (
    ExperimentSpec,
    FactorSpec,
    ManipulationCheck,
    TreatmentMutation,
)

NAMESPACE = "org.scaffold-arena.analysis-plan"


def _planning():
    return importlib.import_module("analysis_v1.planning")


def _factor(*, kind: str = "binary") -> FactorSpec:
    if kind == "binary":
        return FactorSpec(
            factor_id="planning",
            kind="binary",
            levels=(False, True),
            baseline=False,
            description="Explicit planning mechanism.",
            treatment_mutations=(
                TreatmentMutation(
                    target="planning",
                    operation="enable",
                    level=True,
                ),
            ),
            manipulation_checks=(
                ManipulationCheck(
                    factor_id="planning",
                    expected_value=True,
                    oracle="planning-delivery",
                ),
            ),
        )
    return FactorSpec(
        factor_id="planning",
        kind="categorical",
        levels=("none", "brief", "full"),
        baseline="none",
        description="Planning intensity.",
        treatment_mutations=(
            TreatmentMutation(target="planning", operation="select", level="brief"),
            TreatmentMutation(target="planning", operation="select", level="full"),
        ),
        manipulation_checks=(
            ManipulationCheck(
                factor_id="planning",
                expected_value="full",
                oracle="planning-delivery",
            ),
        ),
    )


def _plan(**overrides):
    value = {
        "schema_version": "binary-outcome-v1",
        "primary_outcome": "mission_success",
        "estimand": "risk_difference",
        "baseline_rate": 0.5,
        "minimum_detectable_effect": 0.2,
        "expected_direction": "increase",
        "alpha": 0.05,
        "power": 0.8,
        "comparison_ids": ["planning_main_effect"],
        "intracluster_correlation": 0.0,
        "mean_cluster_size": 1.0,
        "stopping_policy": "fixed_sample",
        "missingness_policy": "complete_case_with_exclusions",
    }
    value.update(overrides)
    return value


def _spec(
    *,
    scenarios: int = 100,
    plan: dict | None = None,
    correction: str = "none",
    design: str = "full",
    kind: str = "binary",
    claim_bearing: bool = True,
) -> ExperimentSpec:
    extensions = {} if plan is None else {NAMESPACE: plan}
    return ExperimentSpec(
        experiment_id="experiment-one",
        study_pack_id="pack-one",
        scenario_ids=tuple(f"scenario-{index}" for index in range(scenarios)),
        harness_ids=("harness-one",),
        factors=(_factor(kind=kind),),
        design=design,
        deterministic_weight=1.0,
        primary_outcomes=("mission_success",),
        multiple_comparison_correction=correction,
        claim_bearing=claim_bearing,
        extensions=extensions,
    )


def test_missing_plan_is_explicitly_not_declared() -> None:
    planning = _planning()
    assessment = planning.assess_analysis_plan(_spec(plan=None, claim_bearing=False))
    assert assessment.status == "NOT_DECLARED"
    assert assessment.declared is False
    assert assessment.required_per_group is None
    assert assessment.available_per_group == 100
    assert "no frozen analysis plan is declared" in assessment.reasons


def test_valid_full_binary_plan_calculates_a_passed_sample_requirement() -> None:
    planning = _planning()
    assessment = planning.assess_analysis_plan(_spec(plan=_plan()))
    assert assessment.status == "PASS"
    assert assessment.declared is True
    assert assessment.nominal_required_per_group is not None
    assert assessment.required_per_group == assessment.nominal_required_per_group
    assert assessment.required_per_group <= assessment.available_per_group == 100
    assert assessment.alpha_per_comparison == 0.05
    assert assessment.design_effect == 1.0
    assert assessment.expected_control_rate == 0.5
    assert assessment.expected_treatment_rate == 0.7
    assert assessment.plan_digest is not None
    assert assessment.reasons == ()


def test_underpowered_plan_holds_before_provider_execution() -> None:
    planning = _planning()
    assessment = planning.assess_analysis_plan(_spec(scenarios=20, plan=_plan()))
    assert assessment.status == "HOLD"
    assert assessment.available_per_group == 20
    assert assessment.required_per_group > assessment.available_per_group
    assert "available observations per pooled group are below the planned requirement" in assessment.reasons


def test_multiple_comparisons_require_an_explicit_correction() -> None:
    planning = _planning()
    assessment = planning.assess_analysis_plan(
        _spec(
            scenarios=500,
            plan=_plan(comparison_ids=["planning", "verification"]),
            correction="none",
        )
    )
    assert assessment.status == "HOLD"
    assert "multiple planned comparisons require an explicit correction" in assessment.reasons


def test_holm_planning_uses_a_conservative_per_comparison_alpha() -> None:
    planning = _planning()
    assessment = planning.assess_analysis_plan(
        _spec(
            scenarios=500,
            plan=_plan(comparison_ids=["planning", "verification"]),
            correction="holm",
        )
    )
    assert assessment.status == "PASS"
    assert assessment.alpha_per_comparison == 0.025
    assert any("conservative Bonferroni" in item for item in assessment.limitations)


def test_cluster_design_effect_inflates_the_required_group_size() -> None:
    planning = _planning()
    independent = planning.assess_analysis_plan(
        _spec(scenarios=500, plan=_plan())
    )
    clustered = planning.assess_analysis_plan(
        _spec(
            scenarios=500,
            plan=_plan(
                intracluster_correlation=0.1,
                mean_cluster_size=5.0,
            ),
        )
    )
    assert clustered.design_effect == 1.4
    assert clustered.required_per_group > independent.required_per_group
    assert clustered.nominal_required_per_group == independent.nominal_required_per_group


def test_invalid_expected_rate_and_malformed_plan_fail_closed() -> None:
    planning = _planning()
    boundary = planning.assess_analysis_plan(
        _spec(plan=_plan(baseline_rate=0.95, minimum_detectable_effect=0.1))
    )
    assert boundary.status == "INVALID"
    assert "expected treatment rate must remain strictly between zero and one" in boundary.reasons

    malformed = planning.assess_analysis_plan(
        _spec(plan={"schema_version": "binary-outcome-v1"})
    )
    assert malformed.status == "INVALID"
    assert malformed.plan_digest is None


def test_unsupported_designs_and_outcomes_return_typed_holds() -> None:
    planning = _planning()
    categorical = planning.assess_analysis_plan(
        _spec(scenarios=500, plan=_plan(), kind="categorical")
    )
    assert categorical.status == "HOLD"
    assert "initial analysis-plan support requires binary factors" in categorical.reasons

    wrong_outcome = planning.assess_analysis_plan(
        _spec(
            scenarios=500,
            plan=_plan(primary_outcome="other_outcome"),
        )
    )
    assert wrong_outcome.status == "HOLD"
    assert "planned primary outcome is not declared by the experiment" in wrong_outcome.reasons


def test_normal_approximation_requires_expected_events_and_non_events() -> None:
    planning = _planning()
    rare = planning.assess_analysis_plan(
        _spec(
            scenarios=500,
            plan=_plan(
                baseline_rate=0.01,
                minimum_detectable_effect=0.01,
            ),
        )
    )
    assert rare.status == "HOLD"
    assert "normal approximation requires at least 10 expected events and non-events per pooled group" in rare.reasons
