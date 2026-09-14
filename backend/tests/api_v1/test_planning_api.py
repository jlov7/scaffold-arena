from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from protocol_v1 import (
    ExperimentSpec,
    FactorSpec,
    ManipulationCheck,
    TreatmentMutation,
)

NAMESPACE = "org.scaffold-arena.analysis-plan"


def _plan() -> dict[str, object]:
    return {
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
    return ExperimentSpec(
        experiment_id="experiment-one",
        study_pack_id="pack-one",
        scenario_ids=tuple(f"scenario-{index}" for index in range(scenarios)),
        harness_ids=("harness-one",),
        factors=(factor,),
        deterministic_weight=1.0,
        primary_outcomes=("mission_success",),
        claim_bearing=include_plan,
        extensions={NAMESPACE: _plan()} if include_plan else {},
    )


def _client() -> TestClient:
    from api.v1 import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_planning_endpoint_is_registered_on_the_public_v1_router() -> None:
    paths = _client().get("/openapi.json").json()["paths"]
    assert "/api/v1/analysis-plans/assess" in paths


def test_planning_endpoint_assesses_strict_frozen_spec_without_provider() -> None:
    response = _client().post(
        "/api/v1/analysis-plans/assess",
        json=_spec().model_dump(mode="json"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "PASS"
    assert payload["declared"] is True
    assert payload["provider_execution_started"] is False
    assert payload["plan_digest"]
    assert payload["required_per_group"] <= payload["available_per_group"]


def test_planning_endpoint_returns_typed_hold_for_underpowered_design() -> None:
    response = _client().post(
        "/api/v1/analysis-plans/assess",
        json=_spec(scenarios=20).model_dump(mode="json"),
    )
    assert response.status_code == 409
    payload = response.json()
    assert payload["verdict"] == "HOLD"
    assert payload["assessment"]["status"] == "HOLD"
    assert payload["assessment"]["provider_execution_started"] is False
    assert "below the planned requirement" in " ".join(
        payload["assessment"]["reasons"]
    )


def test_planning_endpoint_exposes_not_declared_without_upgrading_claims() -> None:
    response = _client().post(
        "/api/v1/analysis-plans/assess",
        json=_spec(include_plan=False).model_dump(mode="json"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "NOT_DECLARED"
    assert payload["declared"] is False
    assert payload["provider_execution_started"] is False


def test_planning_endpoint_rejects_non_protocol_and_extra_fields() -> None:
    response = _client().post(
        "/api/v1/analysis-plans/assess",
        json={"experiment_id": "experiment-one", "raw_results": [1, 2, 3]},
    )
    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_analysis_plan_request",
            "message": "A strict protocol-v1 ExperimentSpec JSON object is required.",
        }
    }
