from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from replay_v1 import CounterfactualReplayRequest
from services_v1.counterfactual import CounterfactualReplayService, HarnessCIService


_EXAMPLE = Path(__file__).parents[3] / "examples" / "counterfactual-replay" / "fixture-replay.json"


def _fixture() -> dict:
    return json.loads(_EXAMPLE.read_text(encoding="utf-8"))


def _repository(tmp_path: Path) -> tuple[ArenaRepository, LocalArtifactStore]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    repository.create_project("Other", project_id="other")
    return repository, LocalArtifactStore(tmp_path / "artifacts")


def _observed_recorded_fixture() -> dict:
    payload = _fixture()
    payload["mode"] = "recorded"
    for pair in payload["pairs"]:
        for branch in (pair["base"], pair["candidate"]):
            branch["usage"] = {
                "state": "observed",
                "provider_usage_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "price_catalog_revision": "catalog-1",
                "input_tokens": 10,
                "output_tokens": 5,
                "cost_usd": 0.01,
            }
    return payload


def _policy(**overrides: object) -> dict:
    policy = {
        "fail_on_new_severe_failures": True,
        "max_quality_regression": 0.0,
        "max_cost_increase_ratio": 0.25,
        "max_latency_increase_ratio": 0.25,
        "required_cohorts": ["development"],
        "unknown_usage": "hold",
        "required_evidence_maturity": "paired_replay",
        "minimum_paired_repetitions": 2,
        "minimum_fidelity": "applied",
        "require_process_safety": True,
        "allow_fixture_evidence": True,
    }
    policy.update(overrides)
    return policy


def _ci_payload(policy: dict | None = None) -> dict:
    return {
        "base_source_digest": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        "candidate_source_digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        "source_changes": [{"path": "harness/config.ts", "diff_text": "+ context compaction keeps the same checkpoint\n- old context"}],
        "policy": policy or _policy(),
    }


def test_contract_rejects_state_drift_hidden_changes_evaluator_leakage_and_causal_claims() -> None:
    payload = _fixture()
    CounterfactualReplayRequest.model_validate(payload)

    hidden = copy.deepcopy(payload)
    hidden["semantic_diff"]["changed_mechanism_ids"] = ["context_compaction", "retry_stopping"]
    with pytest.raises(ValidationError):
        CounterfactualReplayRequest.model_validate(hidden)

    leaked = copy.deepcopy(payload)
    leaked["binding"]["evaluator_digest"] = leaked["binding"]["candidate_genome_digest"]
    with pytest.raises(ValidationError, match="evaluator"):
        CounterfactualReplayRequest.model_validate(leaked)

    unblinded = copy.deepcopy(payload)
    unblinded["binding"]["evaluator_blinded"] = False
    with pytest.raises(ValidationError):
        CounterfactualReplayRequest.model_validate(unblinded)

    overlap = copy.deepcopy(payload)
    overlap["allocation"]["holdout_item_digests"] = overlap["allocation"]["development_item_digests"]
    with pytest.raises(ValidationError, match="holdout overlap"):
        CounterfactualReplayRequest.model_validate(overlap)

    unknown_zero = copy.deepcopy(payload)
    unknown_zero["pairs"][0]["base"]["usage"] = {"state": "unknown", "cost_usd": 0.0}
    with pytest.raises(ValidationError, match="unknown usage"):
        CounterfactualReplayRequest.model_validate(unknown_zero)

    causal = copy.deepcopy(payload)
    causal["analysis_plan"]["causal_claim_requested"] = True
    with pytest.raises(ValidationError):
        CounterfactualReplayRequest.model_validate(causal)


def test_local_replay_is_provider_free_unknown_aware_and_has_a_claim_ceiling() -> None:
    report = CounterfactualReplayService(None, None).local_report(_fixture())  # type: ignore[arg-type]

    assert report["verdict"] == "HOLD"
    assert report["usage_state"] == "unknown"
    assert next(effect for effect in report["effects"] if effect["metric"] == "cost_usd")["point_estimate"] is None
    assert report["provider_execution_started"] is False
    assert report["execution_started"] is False
    assert report["network_requested"] is False
    assert "not causal" in report["claim_ceiling"].lower()
    assert {measure["measure"] for measure in report["conditional_measures"]} == {
        "intention_to_treat", "opportunity", "activation", "fidelity_failure", "treatment_on_the_treated",
    }
    assert all(measure["value"] is None for measure in report["conditional_measures"])
    assert [item["maturity"] for item in report["maturity_ladder"]] == [
        "temporal_correlation",
        "diagnostic_divergence",
        "paired_replay",
        "replicated_intervention",
        "confirmatory_eligibility",
    ]


def test_harness_ci_evaluates_single_mechanism_policy_and_never_promotes_fixture_to_pass() -> None:
    service = HarnessCIService(None, None, replay_service=CounterfactualReplayService(None, None))  # type: ignore[arg-type]

    fixture_report = service.local_report(_fixture(), _ci_payload())
    assert fixture_report["verdict"] == "HOLD"
    assert {check["check_id"]: check["verdict"] for check in fixture_report["checks"]}["usage"] == "HOLD"
    assert fixture_report["provider_execution_started"] is False
    assert "not causal" in fixture_report["claim_ceiling"].lower()

    passing = service.local_report(_observed_recorded_fixture(), _ci_payload())
    assert passing["verdict"] == "PASS"
    assert passing["semantic_diff"]["affected_mechanisms"] == ["context_compaction"]
    assert passing["semantic_diff"]["recommended_packs"] == ["context-survival-v1"]

    failing_replay = _observed_recorded_fixture()
    failing_replay["pairs"][0]["candidate"]["severe_failure_codes"] = ["unsafe_output"]
    failed = service.local_report(failing_replay, _ci_payload())
    assert failed["verdict"] == "FAIL"
    assert {check["check_id"]: check["verdict"] for check in failed["checks"]}["new_severe_failures"] == "FAIL"


def test_persisted_reports_are_content_addressed_idempotent_and_project_scoped(tmp_path: Path) -> None:
    repository, store = _repository(tmp_path)
    replays = CounterfactualReplayService(repository, store, personal_project_id="personal")
    first = replays.create(_observed_recorded_fixture(), project_id=None)
    replay = replays.create(_observed_recorded_fixture(), project_id=None)

    assert first["report_digest"] == replay["report_digest"]
    assert replay["idempotent_replay"] is True
    assert replays.report(first["report_digest"], project_id="personal")["report_digest"] == first["report_digest"]
    with pytest.raises(Exception):
        replays.report(first["report_digest"], project_id="other")

    ci = HarnessCIService(repository, store, personal_project_id="personal", replay_service=replays)
    created = ci.create({**_ci_payload(), "replay_report_digest": first["report_digest"]}, project_id=None)
    repeat = ci.create({**_ci_payload(), "replay_report_digest": first["report_digest"]}, project_id=None)
    assert created["report_digest"] == repeat["report_digest"]
    assert repeat["idempotent_replay"] is True
    assert "context compaction" not in store.get_bytes(created["report_digest"].removeprefix("sha256:")).decode("utf-8")
