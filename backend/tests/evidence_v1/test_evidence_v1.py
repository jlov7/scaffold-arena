from __future__ import annotations

import pytest

from artifacts_v1 import LocalArtifactStore
from evidence_v1 import (
    ClaimMaturity,
    EvidenceClass,
    EvidenceManifest,
    EvidenceVerification,
    ExternalIndependenceAttestation,
    build_decision_brief,
    build_reproduction_receipt,
    create_receipt,
    promote_claim,
    redacted_export,
    verify_evidence,
    verify_receipt,
)
from protocol_v1 import OutcomeVector

H = "a" * 64


def manifest(artifact_hash: str) -> EvidenceManifest:
    return EvidenceManifest(
        experiment_id="experiment-one",
        experiment_hash=H,
        study_pack_hash=H,
        spec_hash=H,
        code_hash=H,
        runtime_hash=H,
        adapter_hash=H,
        model_hash=H,
        price_hash=H,
        evaluator_hashes=(H,),
        artifact_hashes=(artifact_hash,),
        evidence_class=EvidenceClass.FIXTURE,
        claim_ceiling="fixture-only",
    )


def test_receipt_is_deterministic_and_integrity_not_truth(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact = store.put_bytes(b"artifact")
    evidence = manifest(artifact)
    first, second = create_receipt(evidence), create_receipt(evidence)
    assert first.receipt_hash == second.receipt_hash
    ok, errors = verify_receipt(
        first, evidence, store, registered_artifacts={artifact: {"digest": artifact}}
    )
    assert ok and not errors and first.integrity_not_truth is True


def test_tamper_missing_and_db_artifact_mismatch_fail(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact = store.put_bytes(b"artifact")
    evidence, receipt = manifest(artifact), create_receipt(manifest(artifact))
    path = store.uri_for(artifact)
    with open(path, "wb") as handle:
        handle.write(b"tampered")
    ok, errors = verify_receipt(
        receipt, evidence, store, registered_artifacts={artifact: {"digest": "b" * 64}}
    )
    assert not ok and errors
    missing = manifest("c" * 64)
    ok, errors = verify_receipt(create_receipt(missing), missing, store)
    assert not ok and "missing" in errors[0]


def test_self_reproduction_and_claim_promotion_are_blocked() -> None:
    with pytest.raises(ValueError, match="self-assert"):
        build_reproduction_receipt(
            receipt_id="repro-one",
            original_operator_id="op",
            original_authority_id="authority",
            reproducer_operator_id="op",
            reproducer_authority_id="other",
            original_environment_hash=H,
            reproducer_environment_hash=H,
            original_manifest_hash=H,
            reproduced_manifest_hash=H,
            request_independent=True,
        )
    promotion = promote_claim(ClaimMaturity.FIXTURE, ClaimMaturity.HUMAN_CALIBRATED, {})
    assert not promotion.promoted and promotion.claim_ceiling == "FIXTURE"
    unverified = EvidenceVerification(
        evidence_type="local_live",
        receipt_id="receipt-one",
        receipt_hash=H,
        manifest_hash=H,
        verifier_id="verifier",
        verifier_digest=H,
        verified=False,
        errors=("tampered",),
    )
    assert not promote_claim(
        ClaimMaturity.FIXTURE,
        ClaimMaturity.LOCAL_LIVE,
        {"local_live_receipt": unverified},
    ).promoted
    with pytest.raises(ValueError, match="distinct"):
        ExternalIndependenceAttestation(
            reproduction_receipt_hash=H,
            original_operator_id="same",
            original_authority_id="original",
            reproducer_operator_id="same",
            reproducer_authority_id="reproducer",
            attester_authority_id="external",
            attestation_evidence_ref="artifact://attestation",
        )
    with pytest.raises(ValueError, match="distinct"):
        ExternalIndependenceAttestation(
            reproduction_receipt_hash=H,
            original_operator_id="original-operator",
            original_authority_id="original-authority",
            reproducer_operator_id="reproducer-operator",
            reproducer_authority_id="reproducer-authority",
            attester_authority_id="original-authority",
            attestation_evidence_ref="artifact://self-attestation",
        )


def test_verifier_produces_bound_status_not_a_claim_of_truth(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact = store.put_bytes(b"artifact")
    evidence, receipt = manifest(artifact), create_receipt(manifest(artifact))
    status = verify_evidence(
        receipt,
        evidence,
        store,
        evidence_type="local_live",
        verifier_id="receipt-verifier",
        verifier_digest="b" * 64,
    )
    assert (
        status.verified
        and status.manifest_hash == receipt.manifest_hash
        and status.integrity_not_truth
    )


def test_severe_failure_holds_despite_high_score_and_redaction_preserves_hash(
    tmp_path,
) -> None:
    outcome = OutcomeVector(
        episode_id="episode-one",
        mission_success=1.0,
        severe_failures=("policy-break",),
        deterministic={"score": 1.0},
    )
    decision = build_decision_brief(
        brief_id="brief-one",
        outcome=outcome,
        hard_gate_passed=False,
        claim_ceiling="fixture-only",
    )
    assert (
        decision.verdict == "HOLD"
        and decision.blockers[0] == "hard eligibility gate failed"
    )
    store = LocalArtifactStore(tmp_path / "artifacts")
    artifact = store.put_bytes(b"secret=do-not-export")
    exported = redacted_export(manifest(artifact))
    assert exported.artifacts[0].original_hash == artifact
    assert "secret" not in exported.model_dump_json()
