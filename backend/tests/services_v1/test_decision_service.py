from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import update

from evidence_v1 import create_receipt
from persistence_v1.schema import analysis_reports, evidence_receipts
from protocol_v1.canonical import sha256
from services_v1 import DecisionError, DecisionService, EvidenceService
from services_v1.decision import _verification_evidence_type
from tests.services_v1.test_analysis_service import _configuration, _service
from tests.services_v1.test_evidence_service import _manifest


def _decision_service(tmp_path: Path):
    analysis, execution_id = _service(tmp_path)
    analysis.analyze(
        {
            "experiment_id": "experiment-one",
            "execution_id": execution_id,
            "analysis_config": _configuration(),
        },
        project_id="personal",
    )
    artifact = analysis.artifact_store.put_bytes(b"decision-evidence")
    analysis.repository.register_artifact(
        artifact,
        size_bytes=len(b"decision-evidence"),
        storage_uri=analysis.artifact_store.uri_for(artifact),
    )
    binding = analysis.repository.get_execution_evidence_binding("personal", execution_id)
    assert binding is not None
    manifest = _manifest(
        artifact,
        experiment_id=str(binding["experiment_id"]),
        experiment_hash=sha256(binding["definition"]),
        study_pack_hash=str(binding["study_pack_hash"]),
        spec_hash=str(binding["spec_hash"]),
    )
    receipt = create_receipt(manifest, receipt_id="decision-fixture")
    EvidenceService(
        analysis.repository, analysis.artifact_store, personal_project_id="personal"
    ).record_receipt(
        {
            "manifest": manifest.model_dump(mode="json"),
            "receipt": receipt.model_dump(mode="json"),
            "evidence_type": "fixture",
            "execution_id": execution_id,
        },
        project_id="personal",
    )
    report = analysis.repository.get_analysis_report("personal", execution_id)
    assert report is not None
    return DecisionService(
        analysis.repository, analysis.artifact_store, personal_project_id="personal"
    ), report


def _request(report_id: str) -> dict:
    return {
        "analysis_report_id": report_id,
        "risk_constraints": {
            "severe_failure_disposition": "HOLD",
            "require_zero_exclusions": True,
            "require_estimated_effect_for_effect_claims": True,
            "maximum_claim_ceiling": "independent",
        },
        "proposed_claims": [
            {
                "claim_id": "fixture-observation",
                "statement": "The fixture observation was recorded.",
                "kind": "fixture_observation",
                "linked_receipt_ids": ["decision-fixture"],
            }
        ],
    }


def test_decision_reloads_verified_inputs_and_is_idempotent(tmp_path: Path) -> None:
    service, report = _decision_service(tmp_path)
    first = service.create(_request(str(report["id"])), project_id="personal")
    replay = service.create(_request(str(report["id"])), project_id="personal")
    assert first["verdict"] == "PASS"
    assert first["artifact_content"] == "withheld"
    assert replay["idempotent_replay"] is True
    assert service.get(first["decision_brief_id"], project_id="personal")["ledger_ref"].startswith("sha256:")


def test_decision_rejects_caller_maturity_and_changed_replay(tmp_path: Path) -> None:
    service, report = _decision_service(tmp_path)
    request = _request(str(report["id"]))
    service.create(request, project_id="personal")
    changed = json.loads(json.dumps(request))
    changed["proposed_claims"][0]["statement"] = "A changed statement."
    with pytest.raises(DecisionError) as conflict:
        service.create(changed, project_id="personal")
    assert conflict.value.code == "decision_conflict"
    forbidden = json.loads(json.dumps(request))
    forbidden["evidence_receipts"] = []
    with pytest.raises(DecisionError) as rejected:
        service.create(forbidden, project_id="personal")
    assert rejected.value.code == "invalid_decision_request"


def test_report_tamper_holds_before_decision_persistence(tmp_path: Path) -> None:
    service, report = _decision_service(tmp_path)
    with service.repository.transaction() as conn:
        conn.execute(
            update(analysis_reports)
            .where(analysis_reports.c.id == report["id"])
            .values(report_digest="0" * 64)
        )
    with pytest.raises(DecisionError) as held:
        service.create(_request(str(report["id"])), project_id="personal")
    assert held.value.code == "analysis_report_tampered"


def test_self_promoted_human_receipt_is_durably_held(tmp_path: Path) -> None:
    service, report = _decision_service(tmp_path)
    with service.repository.transaction() as conn:
        conn.execute(
            update(evidence_receipts)
            .where(evidence_receipts.c.id == "decision-fixture")
            .values(receipt_kind="human_calibration")
        )
    request = _request(str(report["id"]))
    request["proposed_claims"][0]["kind"] = "human_calibrated_assessment"
    result = service.create(request, project_id="personal")
    assert result["verdict"] == "HOLD"
    assert result["claim_ceiling"] == "no_claim"


def test_legacy_generic_local_live_receipt_is_not_mature(tmp_path: Path) -> None:
    service, report = _decision_service(tmp_path)
    with service.repository.transaction() as conn:
        conn.execute(
            update(evidence_receipts)
            .where(evidence_receipts.c.id == "decision-fixture")
            .values(receipt_kind="local_live")
        )
    request = _request(str(report["id"]))
    request["proposed_claims"][0]["kind"] = "local_live_observation"
    result = service.create(request, project_id="personal")
    assert result["verdict"] == "HOLD"
    assert result["claim_ceiling"] == "no_claim"


def test_derived_receipt_kinds_use_canonical_verification_types() -> None:
    assert _verification_evidence_type("derived_fixture") == "fixture"
    assert _verification_evidence_type("derived_local_live") == "local_live"


def test_null_execution_receipt_is_held(tmp_path: Path) -> None:
    service, report = _decision_service(tmp_path)
    with service.repository.transaction() as conn:
        conn.execute(
            update(evidence_receipts)
            .where(evidence_receipts.c.id == "decision-fixture")
            .values(execution_id=None)
        )
    result = service.create(_request(str(report["id"])), project_id="personal")
    assert result["verdict"] == "HOLD"
    assert result["claim_ceiling"] == "no_claim"


def test_cross_execution_receipt_is_held(tmp_path: Path) -> None:
    service, report = _decision_service(tmp_path)
    other_execution = service.repository.create_execution(str(report["experiment_id"]))
    with service.repository.transaction() as conn:
        conn.execute(
            update(evidence_receipts)
            .where(evidence_receipts.c.id == "decision-fixture")
            .values(execution_id=other_execution)
        )
    result = service.create(_request(str(report["id"])), project_id="personal")
    assert result["verdict"] == "HOLD"
    assert result["claim_ceiling"] == "no_claim"


def test_manifest_mismatch_is_held(tmp_path: Path) -> None:
    service, report = _decision_service(tmp_path)
    row = service.repository.get_evidence_receipt("personal", "decision-fixture")
    assert row is not None
    altered_manifest = _manifest(
        str(row["artifact_hashes"][0]),
        experiment_id="other-experiment",
        experiment_hash="0" * 64,
        study_pack_hash=str(row["manifest_json"]["study_pack_hash"]),
        spec_hash=str(row["manifest_json"]["spec_hash"]),
    )
    altered_receipt = create_receipt(altered_manifest, receipt_id="decision-fixture")
    with service.repository.transaction() as conn:
        conn.execute(
            update(evidence_receipts)
            .where(evidence_receipts.c.id == "decision-fixture")
            .values(
                manifest_json=altered_manifest.model_dump(mode="json"),
                manifest_hash=altered_receipt.manifest_hash,
                receipt_hash=altered_receipt.receipt_hash,
                artifact_hashes=list(altered_receipt.artifact_hashes),
            )
        )
    result = service.create(_request(str(report["id"])), project_id="personal")
    assert result["verdict"] == "HOLD"
    assert result["claim_ceiling"] == "no_claim"
