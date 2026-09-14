import json

import pytest
from pydantic import ValidationError

from analysis_v1.decision import CostStatus
from analysis_v1.engine import (
    AnalysisGates,
    AnalysisInput,
    AnalysisOptions,
    AttemptRecord,
    ExternalFitterReceipt,
    FactorLevel,
    InteractionSpec,
    MainEffectSpec,
    RegisteredFactor,
    build_analysis_report,
)


def attempt(
    identifier: str,
    pair: str,
    cluster: str,
    *,
    a: str = "control",
    b: str = "control",
    success: bool = False,
    variant: str = "clean",
) -> AttemptRecord:
    return AttemptRecord(
        attempt_id=identifier,
        experiment_id="experiment-1",
        task_id=f"task-{pair}",
        task_cluster_id=cluster,
        scaffold_id="scaffold-a",
        pair_id=pair,
        repeat_index=1,
        variant=variant,  # type: ignore[arg-type]
        factor_levels=(
            FactorLevel(factor_id="a", level=a),
            FactorLevel(factor_id="b", level=b),
        ),
        success=success,
        continuous_outcomes=(("quality", float(success)),),
        severe_failures=("unsafe",) if identifier == "a-0" else (),
        auditability=1.0,
        trace_complete=True,
        manipulation_pass=True,
        evaluator_independent=True,
        held_out=True,
        cost_status=CostStatus.RECONCILED,
        cost_usd=0.01,
        provider_usage_ref=f"usage:{identifier}",
        price_reference="prices:v1",
        latency_seconds=1.0,
    )


def payload(
    records: tuple[AttemptRecord, ...],
    *,
    gates: AnalysisGates | None = None,
    **kwargs: object,
) -> AnalysisInput:
    return AnalysisInput(
        experiment_id="experiment-1",
        registered_factors=(
            RegisteredFactor(factor_id="a", levels=("control", "treatment")),
            RegisteredFactor(factor_id="b", levels=("control", "treatment")),
        ),
        attempts=records,
        gates=gates
        or AnalysisGates(preregistered_design=True, comparison_invariants_pass=True),
        options=AnalysisOptions(
            pass_k=2, bootstrap_resamples=100, bootstrap_seed=7, minimum_clusters=2
        ),
        **kwargs,
    )


def test_report_recovers_known_main_and_interaction_effects_with_stable_hash():
    records: list[AttemptRecord] = []
    for index in range(10):
        cluster = "cluster-a" if index < 5 else "cluster-b"
        pair = f"main-{index}"
        records.extend(
            (
                attempt(f"a-{index}", pair, cluster, success=False),
                attempt(f"b-{index}", pair, cluster, a="treatment", success=True),
            )
        )
    for index in range(5):
        cluster = "cluster-a" if index < 3 else "cluster-b"
        pair = f"interaction-{index}"
        records.extend(
            (
                attempt(f"cc-{index}", pair, cluster, success=False),
                attempt(f"tc-{index}", pair, cluster, a="treatment", success=False),
                attempt(f"ct-{index}", pair, cluster, b="treatment", success=False),
                attempt(
                    f"tt-{index}",
                    pair,
                    cluster,
                    a="treatment",
                    b="treatment",
                    success=True,
                ),
            )
        )
    main_source = payload(
        tuple(records[:20]),
        primary_main_effects=(
            MainEffectSpec(
                effect_id="a-main",
                factor_id="a",
                control_level="control",
                treatment_level="treatment",
            ),
        ),
    )
    first = build_analysis_report(main_source)
    second = build_analysis_report(main_source)
    interaction_source = payload(
        tuple(records[20:]),
        secondary_interactions=(
            InteractionSpec(
                interaction_id="a-by-b",
                factor_a="a",
                control_a="control",
                treatment_a="treatment",
                factor_b="b",
                control_b="control",
                treatment_b="treatment",
            ),
        ),
    )
    interaction_report = build_analysis_report(interaction_source)
    assert first.canonical_hash == second.canonical_hash
    assert first.research.status == "HOLD_ADEQUACY"
    assert interaction_report.research.status == "HOLD_ADEQUACY"
    assert first.main_effects[0].estimate == pytest.approx(1.0)
    assert first.main_effects[0].raw_p_value == pytest.approx(0.5)
    assert first.main_effects[0].adjusted_p_value == pytest.approx(0.5)
    assert first.main_effects[0].rejected_after_correction is False
    assert first.main_effects[0].confidence_interval_scope == "marginal"
    assert first.primary_correction == "holm"
    assert interaction_report.secondary_interactions[0].estimate == pytest.approx(1.0)
    assert interaction_report.secondary_interactions[0].raw_p_value == pytest.approx(
        0.5
    )
    assert interaction_report.secondary_interactions[
        0
    ].adjusted_p_value == pytest.approx(0.5)
    assert first.severe_failures_before_composites == (("unsafe", 1),)
    assert first.profiles[0].pass_at_1.denominator == 20
    assert json.loads(first.model_dump_json())["canonical_hash"] == first.canonical_hash


def test_primary_effects_are_id_sorted_and_holm_corrected_from_persisted_pairs():
    records: list[AttemptRecord] = []
    for index in range(4):
        pair = f"factorial-{index}"
        cluster = f"cluster-{index}"
        b_difference = 1.0 if index == 0 else 0.0
        records.extend(
            (
                attempt(f"cc-{index}", pair, cluster).model_copy(
                    update={"continuous_outcomes": (("quality", 0.0),)}
                ),
                attempt(
                    f"tc-{index}", pair, cluster, a="treatment"
                ).model_copy(update={"continuous_outcomes": (("quality", 1.0),)}),
                attempt(
                    f"ct-{index}", pair, cluster, b="treatment"
                ).model_copy(
                    update={"continuous_outcomes": (("quality", b_difference),)}
                ),
                attempt(
                    f"tt-{index}", pair, cluster, a="treatment", b="treatment"
                ).model_copy(
                    update={"continuous_outcomes": (("quality", b_difference + 1.0),)}
                ),
            )
        )
    report = build_analysis_report(
        payload(
            tuple(records),
            primary_main_effects=(
                MainEffectSpec(
                    effect_id="z-b-main",
                    factor_id="b",
                    control_level="control",
                    treatment_level="treatment",
                    outcome="continuous",
                    metric_id="quality",
                ),
                MainEffectSpec(
                    effect_id="a-a-main",
                    factor_id="a",
                    control_level="control",
                    treatment_level="treatment",
                    outcome="continuous",
                    metric_id="quality",
                ),
            ),
        )
    )
    a_main, b_main = report.main_effects
    assert [item.effect_id for item in report.main_effects] == ["a-a-main", "z-b-main"]
    assert a_main.raw_p_value == pytest.approx(0.125)
    assert b_main.raw_p_value == pytest.approx(1.0)
    assert a_main.adjusted_p_value == pytest.approx(0.25)
    assert b_main.adjusted_p_value == pytest.approx(1.0)
    assert (a_main.rejected_after_correction, b_main.rejected_after_correction) == (
        False,
        False,
    )
    assert all(item.confidence_interval_scope == "marginal" for item in report.main_effects)


def test_research_model_holds_without_derived_comparison_invariant_evidence():
    records: list[AttemptRecord] = []
    for index in range(10):
        success = index % 2 == 0
        records.extend((
            attempt(f"null-c-{index}", f"null-{index}", f"cluster-{index % 2}", success=success),
            attempt(f"null-t-{index}", f"null-{index}", f"cluster-{index % 2}", a="treatment", success=success),
        ))
    model = build_analysis_report(payload(
        tuple(records),
        primary_main_effects=(MainEffectSpec(
            effect_id="a-main", factor_id="a", control_level="control", treatment_level="treatment",
        ),),
    ))
    assert model.research.status == "HOLD_ADEQUACY"
    assert model.research.effects == ()
    assert any(
        "derived persisted comparison-invariant evidence is unavailable" in reason
        for reason in model.adequacy.reasons
    )
    inadequate = build_analysis_report(payload(tuple(records[:2])))
    assert inadequate.research.status == "HOLD_ADEQUACY"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("duplicate", "duplicate attempt_id"),
        ("cross-experiment", "cross-experiment contamination"),
        ("unregistered", "unregistered factor level"),
    ],
)
def test_contract_rejects_contaminated_or_unregistered_attempts(
    change: str, message: str
):
    left = attempt("left", "pair", "cluster-a")
    right = attempt("right", "pair", "cluster-a", a="treatment", success=True)
    if change == "duplicate":
        right = right.model_copy(update={"attempt_id": "left"})
    elif change == "cross-experiment":
        right = right.model_copy(update={"experiment_id": "other"})
    else:
        right = right.model_copy(
            update={
                "factor_levels": (
                    FactorLevel(factor_id="a", level="bad"),
                    FactorLevel(factor_id="b", level="control"),
                )
            }
        )
    with pytest.raises(ValidationError, match=message):
        payload((left, right))


def test_contract_rejects_cost_forgery_and_main_effect_rejects_unpaired_data():
    forged = attempt("bad", "pair", "cluster-a").model_dump()
    forged["cost_status"] = CostStatus.UNKNOWN
    with pytest.raises(ValidationError, match="UNKNOWN cost"):
        AttemptRecord(**forged)
    source = payload(
        (attempt("only-control", "pair", "cluster-a"),),
        primary_main_effects=(
            MainEffectSpec(
                effect_id="a",
                factor_id="a",
                control_level="control",
                treatment_level="treatment",
            ),
        ),
    )
    with pytest.raises(ValueError, match="unpaired or duplicated records"):
        build_analysis_report(source)


def test_pass_k_counts_preregistered_episodes_not_constituent_retries():
    episodes = tuple(
        attempt(
            f"final-{index}", "shared-task", "cluster-a", success=index == 2
        ).model_copy(
            update={
                "episode_id": f"episode-{index}",
                "constituent_attempt_ids": (
                    f"physical-{index}-a",
                    f"final-{index}",
                ),
                "repeat_index": index,
            }
        )
        for index in (1, 2, 3)
    )
    report = build_analysis_report(payload(episodes))
    profile = report.profiles[0]
    assert profile.pass_at_1.denominator == 3
    assert profile.pass_at_k.denominator == 1
    assert profile.pass_at_k.numerator == 1.0
    assert profile.pass_at_k.attempt_ids == ("final-1", "final-2")
    assert profile.pass_at_k.constituent_attempt_ids == (
        "physical-1-a", "final-1", "physical-2-a", "final-2"
    )


def test_contract_rejects_duplicate_episode_repetition_profile_factor_unit():
    first = attempt("first", "shared", "cluster-a").model_copy(
        update={"episode_id": "episode-a"}
    )
    duplicate = attempt("second", "shared", "cluster-a").model_copy(
        update={"episode_id": "episode-b"}
    )
    with pytest.raises(ValidationError, match="duplicate episode repetition/profile/factor"):
        payload((first, duplicate))


def test_preregistered_main_effect_rejects_inadequate_task_clusters():
    source = payload(
        (
            attempt("control", "pair", "cluster-a"),
            attempt("treatment", "pair", "cluster-a", a="treatment", success=True),
        ),
        primary_main_effects=(
            MainEffectSpec(
                effect_id="a",
                factor_id="a",
                control_level="control",
                treatment_level="treatment",
            ),
        ),
    )
    with pytest.raises(ValueError, match="inadequate task clusters"):
        build_analysis_report(source)


def test_interaction_effect_is_held_when_hierarchical_effective_sample_gate_fails():
    records: list[AttemptRecord] = []
    for index in range(5):
        records.extend(
            (
                attempt(f"cc-{index}", f"pair-{index}", "cluster-a"),
                attempt(f"tc-{index}", f"pair-{index}", "cluster-a", a="treatment"),
                attempt(f"ct-{index}", f"pair-{index}", "cluster-a", b="treatment"),
                attempt(
                    f"tt-{index}",
                    f"pair-{index}",
                    "cluster-a",
                    a="treatment",
                    b="treatment",
                    success=True,
                ),
            )
        )
    source = payload(
        tuple(records),
        secondary_interactions=(
            InteractionSpec(
                interaction_id="a-by-b",
                factor_a="a",
                control_a="control",
                treatment_a="treatment",
                factor_b="b",
                control_b="control",
                treatment_b="treatment",
                minimum_clusters=2,
            ),
        ),
    )
    report = build_analysis_report(source)
    assert report.secondary_interactions[0].status == "HOLD"
    assert report.secondary_interactions[0].estimate is None


def test_typed_bool_levels_preserve_protocol_factor_values():
    control = attempt("control", "pair-a", "cluster-a").model_copy(
        update={
            "factor_levels": (FactorLevel(factor_id="enabled", level=False),),
        }
    )
    treatment = attempt("treatment", "pair-a", "cluster-a", success=True).model_copy(
        update={
            "factor_levels": (FactorLevel(factor_id="enabled", level=True),),
        }
    )
    source = AnalysisInput(
        experiment_id="experiment-1",
        registered_factors=(
            RegisteredFactor(factor_id="enabled", levels=(False, True)),
        ),
        attempts=(control, treatment),
        gates=AnalysisGates(preregistered_design=True, comparison_invariants_pass=True),
        options=AnalysisOptions(pass_k=2, bootstrap_resamples=10, minimum_clusters=2),
        primary_main_effects=(
            MainEffectSpec(
                effect_id="enabled",
                factor_id="enabled",
                control_level=False,
                treatment_level=True,
            ),
        ),
    )
    assert dict(source.attempts[0].factors)["enabled"] is False
    assert source.primary_main_effects[0].treatment_level is True


def test_clean_stress_tax_uses_analysis_pair_id_without_equal_scenario_ids():
    records = (
        attempt("clean-a", "analysis-pair-a", "cluster-a", success=True).model_copy(
            update={"task_id": "clean-a"}
        ),
        attempt(
            "stress-a", "analysis-pair-a", "cluster-a", success=False, variant="stress"
        ).model_copy(update={"task_id": "stress-a"}),
        attempt("clean-b", "analysis-pair-b", "cluster-b", success=True).model_copy(
            update={"task_id": "clean-b"}
        ),
        attempt(
            "stress-b", "analysis-pair-b", "cluster-b", success=False, variant="stress"
        ).model_copy(update={"task_id": "stress-b"}),
    )
    report = build_analysis_report(payload(records))
    tax = report.clean_vs_stressed_tax[0]
    assert tax.status == "ESTIMATED"
    assert tax.effective_pairs == 2
    assert tax.estimate == pytest.approx(-1.0)


def test_interaction_spec_rejects_caller_supplied_p_values():
    with pytest.raises(ValidationError, match="raw_p_value"):
        InteractionSpec.model_validate(
            {
                "interaction_id": "a-by-b",
                "factor_a": "a",
                "control_a": "control",
                "treatment_a": "treatment",
                "factor_b": "b",
                "control_b": "control",
                "treatment_b": "treatment",
                "raw_p_value": 0.001,
            }
        )


def test_primary_main_effect_spec_rejects_caller_supplied_p_values():
    with pytest.raises(ValidationError, match="raw_p_value"):
        MainEffectSpec.model_validate(
            {
                "effect_id": "a-main",
                "factor_id": "a",
                "control_level": "control",
                "treatment_level": "treatment",
                "raw_p_value": 0.001,
            }
        )


@pytest.mark.parametrize(
    "failed_gate",
    [
        "preregistered_design",
        "comparison_invariants_pass",
        "manipulation_pass",
        "trace_complete",
        "evaluator_independent",
        "held_out",
    ],
)
def test_external_mixed_effect_receipt_never_bypasses_an_adequacy_gate(
    failed_gate: str,
):
    records: list[AttemptRecord] = []
    for index in range(10):
        cluster = "cluster-a" if index < 5 else "cluster-b"
        records.extend(
            (
                attempt(f"control-{index}", f"pair-{index}", cluster),
                attempt(
                    f"treatment-{index}",
                    f"pair-{index}",
                    cluster,
                    a="treatment",
                    success=True,
                ),
            )
        )
    if failed_gate in {
        "manipulation_pass",
        "trace_complete",
        "evaluator_independent",
        "held_out",
    }:
        records[0] = records[0].model_copy(update={failed_gate: False})
        if failed_gate in {"manipulation_pass", "trace_complete"}:
            records[2] = records[2].model_copy(update={failed_gate: False})
    digest = "a" * 64
    gates = AnalysisGates(
        preregistered_design=failed_gate != "preregistered_design",
        comparison_invariants_pass=failed_gate != "comparison_invariants_pass",
        external_fitter_receipt=ExternalFitterReceipt(
            receipt_id="fit-1",
            fitter="R",
            fitter_version="4.0",
            input_digest=digest,
            output_digest=digest,
            result_ref="evidence:fit-1",
        ),
    )
    source = payload(
        tuple(records),
        gates=gates,
        primary_main_effects=(
            MainEffectSpec(
                effect_id="a-main",
                factor_id="a",
                control_level="control",
                treatment_level="treatment",
            ),
        ),
    )
    report = build_analysis_report(source)
    assert report.adequacy.claim_level == "DESCRIPTIVE_ONLY"
    assert report.adequacy.mixed_effect_status == "NOT_RUN"
    assert report.adequacy.external_fitter_receipt is None
    assert report.research.status == "HOLD_ADEQUACY"
