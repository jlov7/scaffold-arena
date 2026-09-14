from __future__ import annotations

import json
from pathlib import Path

import pytest

from protocol_v1 import (
    ExperimentSpec,
    FactorSpec,
    ManipulationCheck,
    TreatmentMutation,
)

NAMESPACE = "org.scaffold-arena.analysis-plan"


def _spec(*, scenarios: int = 100, include_plan: bool = True) -> ExperimentSpec:
    factor = FactorSpec(
        factor_id="planning",
        kind="binary",
        levels=(False, True),
        baseline=False,
        description="Explicit planning mechanism.",
        treatment_mutations=(
            TreatmentMutation(target="planning", operation="enable", level=True),
        ),
        manipulation_checks=(
            ManipulationCheck(
                factor_id="planning",
                expected_value=True,
                oracle="planning-delivery",
            ),
        ),
    )
    plan = {
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
    return ExperimentSpec(
        experiment_id="experiment-one",
        study_pack_id="pack-one",
        scenario_ids=tuple(f"scenario-{index}" for index in range(scenarios)),
        harness_ids=("harness-one",),
        factors=(factor,),
        deterministic_weight=1.0,
        primary_outcomes=("mission_success",),
        claim_bearing=include_plan,
        extensions={NAMESPACE: plan} if include_plan else {},
    )


def _write(path: Path, spec: ExperimentSpec) -> None:
    path.write_text(
        json.dumps(spec.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )


def _main(argv: list[str]) -> int:
    from arena_cli.entrypoint import main

    return main(argv)


def test_installed_cli_help_exposes_analysis_plan(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        _main(["experiment", "--help"])
    assert raised.value.code == 0
    assert "analysis-plan" in capsys.readouterr().out


def test_analysis_plan_cli_emits_pass_json_without_provider(
    tmp_path: Path,
    capsys,
) -> None:
    path = tmp_path / "experiment.json"
    _write(path, _spec())

    assert _main(["experiment", "analysis-plan", "--spec", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "PASS"
    assert payload["assessment"]["status"] == "PASS"
    assert payload["assessment"]["provider_execution_started"] is False
    assert payload["experiment_id"] == "experiment-one"


def test_analysis_plan_cli_returns_hold_exit_code_for_underpowered_design(
    tmp_path: Path,
    capsys,
) -> None:
    path = tmp_path / "experiment.json"
    _write(path, _spec(scenarios=20))

    assert _main(["experiment", "analysis-plan", "--spec", str(path)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "HOLD"
    assert payload["assessment"]["status"] == "HOLD"
    assert payload["provider_execution_started"] is False


def test_analysis_plan_cli_reports_not_declared_as_hold(
    tmp_path: Path,
    capsys,
) -> None:
    path = tmp_path / "experiment.json"
    _write(path, _spec(include_plan=False))

    assert _main(["experiment", "analysis-plan", "--spec", str(path)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "HOLD"
    assert payload["assessment"]["status"] == "NOT_DECLARED"
    assert payload["provider_execution_started"] is False


def test_analysis_plan_cli_rejects_invalid_json_without_traceback(
    tmp_path: Path,
    capsys,
) -> None:
    path = tmp_path / "experiment.json"
    path.write_text("not-json", encoding="utf-8")

    assert _main(["experiment", "analysis-plan", "--spec", str(path)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "assessment": None,
        "code": "invalid_analysis_plan_request",
        "provider_execution_started": False,
        "verdict": "HOLD",
    }
