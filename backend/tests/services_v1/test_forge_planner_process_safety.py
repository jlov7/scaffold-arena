from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update

from artifacts_v1 import LocalArtifactStore
from forge_v1 import ForgeEvaluation, ForgeProposal, NextBestExperimentRequest, ProcessSafetyRequest
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import forge_evaluations, forge_proposals
from services_v1.forge import ExperimentPlannerService, ForgeError, ForgeService, ProcessSafetyService


def digest(value: int) -> str:
    token = f"{value:x}"
    return f"sha256:{(token * 64)[:64]}"


def proposal() -> dict:
    return {
        "proposal_id": "proposal-one",
        "proposer_identity": "proposer-one",
        "source_provenance_digest": digest(1),
        "base_genome_digest": digest(2),
        "candidate_genome_digest": digest(3),
        "mechanism_change": {
            "mechanism_id": "context_compaction",
            "base_mechanism_digest": digest(4),
            "candidate_mechanism_digest": digest(5),
            "patch_or_config_digest": digest(6),
            "declared_change_count": 1,
        },
        "falsifiable_prediction": {"metric_id": "quality", "direction": "increase", "threshold": 0.02, "prediction_digest": digest(7)},
        "expected_tradeoff": {"quality": "improve", "safety": "neutral", "cost": "increase", "latency": "increase", "rationale_digest": digest(8)},
        "triggering_evidence_digests": [digest(9)],
        "rollback": {"rollback_id": "rollback-one", "rollback_digest": digest(10), "recovery_plan_digest": digest(11)},
        "requested_claim_scope": "product_control",
        "untrusted": True,
        "execution_requested": False,
        "automatic_merge_requested": False,
        "self_evaluation_requested": False,
        "scalar_optimization_requested": False,
    }


_OUTCOMES = [
    "unnecessary_sensitive_data_access", "prohibited_tool", "permission_escalation", "network_egress", "secret_exposure",
    "unsafe_intermediate_artifact", "policy_bypassing_retry", "sensitive_persistent_memory", "trace_log_leakage", "cleanup_failure",
]


def process_safety() -> dict:
    return {
        "request_id": "safety-one",
        "policy": {
            "policy_digest": digest(20),
            "maximum_sensitivity": "SECRET",
            "allowed_tool_digests": [],
            "allow_external_egress": False,
            "maximum_delegation_depth": 0,
            "secret_retention": "digests_and_redacted_manifests_only",
            "required_cleanup": True,
        },
        "flows": [{
            "flow_id": "flow-one", "source": "artifact", "destination": "context", "sensitivity": "PUBLIC",
            "content_digest": digest(21), "redacted_manifest_digest": digest(22), "tool_digest": None, "delegation_depth": 0,
        }],
        "outcomes": [{"outcome_type": outcome, "state": "NOT_OBSERVED", "evidence_digest": digest(index + 23)} for index, outcome in enumerate(_OUTCOMES)],
        "transitions": [{"from_state": "DRAFT", "to_state": "PENDING_APPROVAL", "transition_digest": digest(40)}],
        "cleanup_receipt_digest": digest(41),
        "source_manifest_digest": digest(42),
        "execution_started": False,
        "network_requested": False,
    }


def planner() -> dict:
    return {
        "request_id": "plan-one",
        "mode": "exploratory",
        "mechanisms": [
            {"mechanism_id": "context_compaction", "uncertainty": 0.8, "expected_effect": 0.2, "interaction_uncertainty": 0.1},
            {"mechanism_id": "retry_stopping", "uncertainty": 0.4, "expected_effect": 0.05, "interaction_uncertainty": 0.0},
        ],
        "coverage": [{"coverage_id": "research", "fraction": 0.8}, {"coverage_id": "safety", "fraction": 0.6}],
        "prior_evidence": [{"evidence_digest": digest(50), "mechanism_id": "context_compaction", "evidence_strength": 0.2}],
        "candidate_designs": [
            {"design_id": "design-context", "mechanism_id": "context_compaction", "coverage_ids": ["research", "safety"], "cost_per_attempt_usd": 1.0, "minimum_attempts": 2, "maximum_attempts": 5, "risk": 0.2, "assumptions": ["Fixed evaluator."]},
            {"design_id": "design-retry", "mechanism_id": "retry_stopping", "coverage_ids": ["research"], "cost_per_attempt_usd": 10.0, "minimum_attempts": 2, "maximum_attempts": 4, "risk": 0.1, "assumptions": ["Pinned cost catalog."]},
        ],
        "minimum_detectable_effect": 0.1,
        "remaining_budget_usd": 6.0,
        "maximum_risk": 0.3,
        "frozen_analysis_plan_digest": None,
        "exploratory_adaptation": False,
        "source_evidence_digests": [digest(51)],
        "execution_requested": False,
        "automatic_admission_requested": False,
    }


def evaluation(proposal_digest: str, safety_digest: str) -> dict:
    plan_digest = digest(62)
    evaluator_config = digest(63)
    return {
        "evaluation_id": "evaluation-one",
        "proposal_digest": proposal_digest,
        "evaluator_identity": "evaluator-one",
        "evaluator_identity_digest": digest(60),
        "cohorts": {
            "cohort_partition_digest": digest(61),
            "development_item_digests": [digest(64)],
            "sealed_holdout_manifest_digest": digest(65),
            "sealed_holdout_runner_receipt_digest": digest(66),
            "safety_item_digests": [digest(67)],
            "transfer_cohorts": [{"cohort_id": "transfer-one", "item_digests": [digest(68)]}],
        },
        "frozen_plan": {
            "experiment_plan_digest": digest(69), "analysis_plan_digest": digest(70), "evaluator_configuration_digest": evaluator_config,
            "stopping_rule_digest": digest(71), "cancellation_policy_digest": digest(72), "recovery_policy_digest": digest(73),
            "matched_compute_budget_digest": plan_digest, "deterministic_score_weight": 0.7, "exploratory_adaptation": False, "frozen": True,
        },
        "result_evidence_digests": [digest(74)],
        "effects": [{"metric_id": "quality", "state": "observed", "point_estimate": 0.03, "ci95_low": -0.01, "ci95_high": 0.07, "minimum_detectable_effect": 0.02}],
        "failures": [], "failure_manifest_digest": digest(75),
        "usage": {"state": "observed", "usage_digest": digest(76), "cost_usd": 1.2, "latency_ms": 123},
        "matched_controls": [
            {"control_kind": kind, "control_genome_digest": digest(77 + index), "result_digest": digest(81 + index), "compute_budget_digest": plan_digest, "evaluator_configuration_digest": evaluator_config}
            for index, kind in enumerate(["random_search", "heuristic_edits", "no_change", "matched_compute_test_time_search"])
        ],
        "process_safety_report_digest": safety_digest,
        "workflow": {"state": "completed", "interruption_evidence_digest": None, "recovery_evidence_digest": None, "rollback_state": "not_needed", "rollback_evidence_digest": None},
        "outcome": "INCONCLUSIVE",
        "admission": {"authority_kind": "human", "admitting_identity": "owner-one", "policy_digest": digest(85), "decision_evidence_digest": digest(86), "outcome": "INCONCLUSIVE", "merge_authorized": False, "execution_authorized": False},
        "sealed_holdout_inspected": False, "evaluator_changed": False, "failures_erased": False, "self_graded": False,
        "self_promoted": False, "automatic_merge": False, "execution_started": False, "network_requested": False,
    }


def services(tmp_path):
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    repository.create_project("Other", project_id="other")
    store = LocalArtifactStore(tmp_path / "artifacts")
    return repository, ForgeService(repository, store, personal_project_id="personal"), ExperimentPlannerService(repository, store, personal_project_id="personal"), ProcessSafetyService(repository, store, personal_project_id="personal")


def test_strict_proposal_contract_forbids_merge_multi_change_and_same_genome() -> None:
    ForgeProposal.model_validate(proposal())
    invalid = copy.deepcopy(proposal())
    invalid["automatic_merge_requested"] = True
    with pytest.raises(ValidationError):
        ForgeProposal.model_validate(invalid)
    invalid = copy.deepcopy(proposal())
    invalid["candidate_genome_digest"] = invalid["base_genome_digest"]
    with pytest.raises(ValidationError, match="Genome"):
        ForgeProposal.model_validate(invalid)


def test_planner_is_budget_and_risk_constrained_and_confirmatory_is_frozen(tmp_path) -> None:
    _, _, planner_service, _ = services(tmp_path)
    report = planner_service.local_report(planner())
    assert report["verdict"] == "READY"
    assert [item["proposed_design"]["design_id"] for item in report["recommendations"]] == ["design-context"]
    assert report["excluded_designs"] == [{"design_id": "design-retry", "reason": "Remaining budget cannot fund the minimum attempt count."}]
    assert report["execution_started"] is False
    assert "not an execution" in report["claim_ceiling"].lower()
    invalid = copy.deepcopy(planner())
    invalid.update({"mode": "confirmatory", "frozen_analysis_plan_digest": digest(90), "exploratory_adaptation": True})
    with pytest.raises(ValidationError):
        NextBestExperimentRequest.model_validate(invalid)


def test_process_safety_is_digest_only_and_fails_closed_for_egress(tmp_path) -> None:
    _, _, _, safety_service = services(tmp_path)
    report = safety_service.local_report(process_safety())
    assert report["verdict"] == "PASS"
    assert report["raw_sensitive_content_retained"] is False
    assert report["execution_started"] is False
    assert {item["check_id"] for item in report["checks"]} >= {"data_scope", "tool_allowlist", "network_egress", "delegation_depth", "secret_handling", "plan_transitions"}
    unsafe = copy.deepcopy(process_safety())
    unsafe["flows"][0]["destination"] = "external"
    unsafe["flows"][0]["sensitivity"] = "SECRET"
    unsafe["flows"][0]["content_digest"] = None
    unsafe["flows"][0]["redacted_manifest_digest"] = digest(91)
    result = safety_service.local_report(unsafe)
    assert result["verdict"] == "FAIL"
    assert next(item for item in result["checks"] if item["check_id"] == "network_egress")["verdict"] == "FAIL"
    raw = copy.deepcopy(process_safety())
    raw["flows"][0]["raw_content"] = "TOP_SECRET_DO_NOT_STORE"
    with pytest.raises(ValidationError):
        ProcessSafetyRequest.model_validate(raw)


def test_forge_requires_independent_approval_safety_and_preserves_immutable_receipt(tmp_path) -> None:
    repository, forge, _, safety = services(tmp_path)
    created = forge.create_proposal(proposal(), project_id=None)
    again = forge.create_proposal(proposal(), project_id=None)
    assert again["idempotent_replay"] is True
    assert created["execution_started"] is False
    self_approval = {"proposal_digest": created["proposal_digest"], "approver_identity": "proposer-one", "authority_kind": "human", "decision": "APPROVED", "policy_digest": digest(100), "decision_evidence_digest": digest(101), "execution_authorized": False, "merge_authorized": False}
    with pytest.raises(ForgeError, match="cannot approve"):
        forge.approve(created["proposal_digest"], self_approval, project_id=None)
    approved = {**self_approval, "approver_identity": "approver-one"}
    forge.approve(created["proposal_digest"], approved, project_id=None)
    safety_report = safety.create(process_safety(), project_id=None)
    evaluation_payload = evaluation(created["proposal_digest"], safety_report["report_digest"])
    receipt = forge.create_evaluation(evaluation_payload, project_id=None)
    assert receipt["outcome"] == "INCONCLUSIVE"
    assert receipt["immutable"] is True
    assert receipt["automatic_merge"] is False
    assert forge.proposal(created["proposal_digest"], project_id=None)["state"] == "INCONCLUSIVE"
    assert forge.create_evaluation(evaluation_payload, project_id=None)["idempotent_replay"] is True
    assert forge.receipt(receipt["receipt_digest"], project_id="personal")["receipt_digest"] == receipt["receipt_digest"]
    with pytest.raises(ForgeError):
        forge.receipt(receipt["receipt_digest"], project_id="other")
    with repository.transaction() as conn:
        with pytest.raises(Exception):
            conn.execute(update(forge_evaluations).values(outcome="ADMITTED"))
    unseparated = evaluation(created["proposal_digest"], safety_report["report_digest"])
    unseparated["evaluator_identity"] = "proposer-one"
    with pytest.raises(ForgeError, match="evaluator"):
        forge.create_evaluation(unseparated, project_id=None)
    second_evaluation = evaluation(created["proposal_digest"], safety_report["report_digest"])
    second_evaluation["evaluation_id"] = "evaluation-two"
    with pytest.raises(ForgeError) as error:
        forge.create_evaluation(second_evaluation, project_id=None)
    assert error.value.code == "forge_proposal_not_approved"
    with repository.engine.connect() as conn:
        assert conn.execute(select(forge_proposals.c.state).where(forge_proposals.c.proposal_digest == created["proposal_digest"].removeprefix("sha256:"))).scalar_one() == "INCONCLUSIVE"


def test_admitted_receipt_stays_record_only_and_transitions_proposal(tmp_path) -> None:
    _, forge, _, safety = services(tmp_path)
    admitted_proposal = copy.deepcopy(proposal())
    admitted_proposal["proposal_id"] = "proposal-admitted"
    created = forge.create_proposal(admitted_proposal, project_id=None)
    forge.approve(created["proposal_digest"], {
        "proposal_digest": created["proposal_digest"], "approver_identity": "approver-one", "authority_kind": "human",
        "decision": "APPROVED", "policy_digest": digest(120), "decision_evidence_digest": digest(121),
        "execution_authorized": False, "merge_authorized": False,
    }, project_id=None)
    safety_report = safety.create(process_safety(), project_id=None)
    admitted = evaluation(created["proposal_digest"], safety_report["report_digest"])
    admitted["evaluation_id"] = "evaluation-admitted"
    admitted["outcome"] = "ADMITTED"
    admitted["admission"]["outcome"] = "ADMITTED"
    receipt = forge.create_evaluation(admitted, project_id=None)
    assert forge.proposal(created["proposal_digest"], project_id=None)["state"] == "ADMITTED"
    assert receipt["execution_started"] is False
    assert receipt["automatic_merge"] is False
    assert "record-only policy outcome" in receipt["claim_ceiling"]
    assert "evidence validity" in receipt["claim_ceiling"]
    assert "security assessment" in receipt["claim_ceiling"]


def test_receipt_read_maps_missing_and_corrupt_artifacts_to_forge_error(tmp_path, monkeypatch) -> None:
    _, forge, _, safety = services(tmp_path)
    created = forge.create_proposal(proposal(), project_id=None)
    forge.approve(created["proposal_digest"], {
        "proposal_digest": created["proposal_digest"], "approver_identity": "approver-one", "authority_kind": "human",
        "decision": "APPROVED", "policy_digest": digest(122), "decision_evidence_digest": digest(123),
        "execution_authorized": False, "merge_authorized": False,
    }, project_id=None)
    safety_report = safety.create(process_safety(), project_id=None)
    receipt = forge.create_evaluation(evaluation(created["proposal_digest"], safety_report["report_digest"]), project_id=None)

    def missing(_: str) -> bytes:
        raise FileNotFoundError("receipt missing")

    monkeypatch.setattr(forge.artifact_store, "get_bytes", missing)
    with pytest.raises(ForgeError) as missing_error:
        forge.receipt(receipt["receipt_digest"], project_id=None)
    assert missing_error.value.code == "evolution_receipt_artifact_invalid"
    assert missing_error.value.status_code == 500

    monkeypatch.setattr(forge.artifact_store, "get_bytes", lambda _: b"not-json")
    with pytest.raises(ForgeError) as corrupt_error:
        forge.receipt(receipt["receipt_digest"], project_id=None)
    assert corrupt_error.value.code == "evolution_receipt_artifact_invalid"
    assert corrupt_error.value.status_code == 500


def test_rejected_proposal_cannot_be_evaluated(tmp_path) -> None:
    _, forge, _, _ = services(tmp_path)
    rejected_proposal = copy.deepcopy(proposal())
    rejected_proposal["proposal_id"] = "proposal-two"
    created = forge.create_proposal(rejected_proposal, project_id=None)
    forge.approve(created["proposal_digest"], {
        "proposal_digest": created["proposal_digest"], "approver_identity": "approver-one", "authority_kind": "policy",
        "decision": "REJECTED", "policy_digest": digest(108), "decision_evidence_digest": digest(109),
        "execution_authorized": False, "merge_authorized": False,
    }, project_id=None)
    with pytest.raises(ForgeError, match="approval is required"):
        forge.create_evaluation(evaluation(created["proposal_digest"], digest(110)), project_id=None)


def test_interrupted_work_requires_evidence_and_cannot_be_admitted() -> None:
    candidate = evaluation(digest(110), digest(111))
    candidate["workflow"] = {"state": "interrupted", "interruption_evidence_digest": digest(112), "recovery_evidence_digest": None, "rollback_state": "recorded", "rollback_evidence_digest": digest(113)}
    candidate["outcome"] = "ADMITTED"
    candidate["admission"]["outcome"] = "ADMITTED"
    with pytest.raises(ValidationError, match="cannot be admitted"):
        ForgeEvaluation.model_validate(candidate)
    recovered = evaluation(digest(114), digest(115))
    recovered["workflow"] = {"state": "recovered", "interruption_evidence_digest": digest(116), "recovery_evidence_digest": digest(117), "rollback_state": "recorded", "rollback_evidence_digest": digest(118)}
    assert ForgeEvaluation.model_validate(recovered).workflow.state == "recovered"
