from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, select, update

from artifacts_v1 import LocalArtifactStore
from evidence_v1 import EvidenceClass, EvidenceManifest, create_receipt
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import (
    attempts,
    evaluations,
    evidence_receipt_artifacts,
    executions,
    jobs,
    reproductions,
)
from protocol_v1 import ExperimentSpec
from protocol_v1 import freeze_experiment as freeze_protocol_experiment
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from services_v1 import EvidenceError, EvidenceService


def _manifest(
    artifact: str,
    *,
    experiment_id: str = "experiment-one",
    experiment_hash: str = "a" * 64,
    study_pack_hash: str = "b" * 64,
    spec_hash: str = "c" * 64,
    evidence_class: EvidenceClass = EvidenceClass.FIXTURE,
    claim_ceiling: str = "fixture custody/integrity only; no correctness claim",
) -> EvidenceManifest:
    return EvidenceManifest(
        experiment_id=experiment_id,
        experiment_hash=experiment_hash,
        study_pack_hash=study_pack_hash,
        spec_hash=spec_hash,
        code_hash="d" * 64,
        runtime_hash="e" * 64,
        adapter_hash="f" * 64,
        model_hash="1" * 64,
        price_hash="2" * 64,
        evaluator_hashes=("3" * 64,),
        artifact_hashes=(artifact,),
        evidence_class=evidence_class,
        claim_ceiling=claim_ceiling,
    )


@pytest.fixture
def evidence_service(tmp_path: Path) -> tuple[EvidenceService, ArenaRepository, LocalArtifactStore]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    repository.create_project("Other", project_id="other")
    store = LocalArtifactStore(tmp_path / "artifacts")
    return EvidenceService(repository, store, personal_project_id="personal"), repository, store


def _record(service: EvidenceService, repository: ArenaRepository, store: LocalArtifactStore, *, receipt_id: str = "receipt-one") -> tuple[dict, EvidenceManifest]:
    artifact = store.put_bytes(b"evidence")
    repository.register_artifact(artifact, size_bytes=8, storage_uri=store.uri_for(artifact))
    manifest = _manifest(artifact)
    receipt = create_receipt(manifest, receipt_id=receipt_id)
    result = service.record_receipt(
        {"manifest": manifest.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"), "evidence_type": "fixture", "execution_id": None},
        project_id="personal",
    )
    return result, manifest


def _bind_evaluator_result_artifacts(analysis) -> None:
    with analysis.repository.transaction() as conn:
        rows = conn.execute(select(evaluations)).mappings().all()
        for row in rows:
            result_bytes = canonical_json(row["result"])
            result_hash = sha256_bytes(result_bytes)
            artifact = analysis.artifact_store.put_bytes(result_bytes)
            analysis.repository.register_artifact(
                artifact, size_bytes=len(result_bytes), storage_uri=analysis.artifact_store.uri_for(artifact),
            )
            conn.execute(
                update(evaluations).where(evaluations.c.id == row["id"]).values(
                    result_hash=result_hash, result_artifact_digest=artifact,
                )
            )


@pytest.mark.parametrize(("evidence_type", "evidence_class"), [
    ("fixture", EvidenceClass.FIXTURE),
    ("local_live", EvidenceClass.LOCAL_LIVE),
    ("reproduction", EvidenceClass.REPLICATED),
    ("cross_model", EvidenceClass.CROSS_MODEL),
    ("human_calibration", EvidenceClass.HUMAN_CALIBRATED),
    ("independent_reproduction", EvidenceClass.INDEPENDENTLY_REPRODUCED),
])
def test_evidence_type_requires_its_exact_manifest_class(
    evidence_service, evidence_type: str, evidence_class: EvidenceClass,
) -> None:
    service, repository, store = evidence_service
    artifact = store.put_bytes(evidence_type.encode())
    repository.register_artifact(artifact, size_bytes=len(evidence_type), storage_uri=store.uri_for(artifact))
    ceiling = {
        EvidenceClass.FIXTURE: "fixture custody/integrity only; no correctness claim",
        EvidenceClass.LOCAL_LIVE: "local-live custody/integrity only; no correctness claim",
    }.get(evidence_class, "caller-controlled broader claim")
    manifest = _manifest(artifact, evidence_class=evidence_class, claim_ceiling=ceiling)
    receipt = create_receipt(manifest, receipt_id=f"valid-{evidence_type}")
    valid = {"manifest": manifest.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"), "evidence_type": evidence_type, "execution_id": None}
    if evidence_class is EvidenceClass.FIXTURE:
        assert service.record_receipt(valid, project_id="personal")["receipt_id"] == receipt.receipt_id
    else:
        with pytest.raises(EvidenceError) as direct_promotion:
            service.record_receipt(valid, project_id="personal")
        assert direct_promotion.value.code == "evidence_admission_hold"

    mismatch = manifest.model_copy(update={"evidence_class": EvidenceClass.FIXTURE if evidence_class is not EvidenceClass.FIXTURE else EvidenceClass.LOCAL_LIVE})
    bad_receipt = create_receipt(mismatch, receipt_id=f"invalid-{evidence_type}")
    with pytest.raises(EvidenceError) as rejected:
        service.record_receipt(
            {"manifest": mismatch.model_dump(mode="json"), "receipt": bad_receipt.model_dump(mode="json"), "evidence_type": evidence_type, "execution_id": None},
            project_id="personal",
        )
    assert rejected.value.code == ("evidence_class_mismatch" if evidence_class is EvidenceClass.FIXTURE else "evidence_admission_hold")


def test_admission_rejects_exaggerated_caller_claim_ceiling(evidence_service) -> None:
    service, repository, store = evidence_service
    artifact = store.put_bytes(b"exaggerated")
    repository.register_artifact(artifact, size_bytes=11, storage_uri=store.uri_for(artifact))
    manifest = _manifest(artifact, claim_ceiling="independently reproduced and correct")
    receipt = create_receipt(manifest, receipt_id="exaggerated")
    with pytest.raises(EvidenceError) as rejected:
        service.record_receipt(
            {"manifest": manifest.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"), "evidence_type": "fixture", "execution_id": None},
            project_id="personal",
        )
    assert rejected.value.code == "claim_ceiling_mismatch"


def _frozen_execution(repository: ArenaRepository, store: LocalArtifactStore) -> tuple[str, str, EvidenceManifest]:
    pack_content = b"frozen-pack"
    pack_digest = store.put_bytes(pack_content)
    repository.register_artifact(pack_digest, size_bytes=len(pack_content), storage_uri=store.uri_for(pack_digest))
    pack_id = repository.create_study_pack_version("personal", "pack", "1.0.0", pack_digest)
    experiment_id = repository.create_experiment("personal", pack_id, "bound", owner_approval="approved", experiment_id="bound-experiment")
    frozen = freeze_protocol_experiment(
        ExperimentSpec(
            experiment_id=experiment_id, study_pack_id="pack", scenario_ids=("scenario",), harness_ids=("harness",),
            deterministic_weight=0.7, owner_approval="approved",
        ),
        pack_digest,
    )
    definition = frozen.model_dump(mode="json")
    repository.freeze_experiment(
        experiment_id, expected_definition={}, frozen_definition=definition,
        spec_hash=str(frozen.freeze_hash), study_pack_hash=pack_digest,
    )
    execution_id = repository.create_execution(experiment_id)
    evidence_content = b"bound-evidence"
    artifact = store.put_bytes(evidence_content)
    repository.register_artifact(artifact, size_bytes=len(evidence_content), storage_uri=store.uri_for(artifact))
    return execution_id, experiment_id, _manifest(
        artifact, experiment_id=experiment_id, experiment_hash=sha256(definition),
        study_pack_hash=pack_digest, spec_hash=str(frozen.freeze_hash),
    )


def test_execution_bound_receipt_requires_exact_frozen_provenance(evidence_service) -> None:
    service, repository, store = evidence_service
    execution_id, _, manifest = _frozen_execution(repository, store)
    receipt = create_receipt(manifest, receipt_id="bound-receipt")
    payload = {"manifest": manifest.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"), "evidence_type": "fixture", "execution_id": execution_id}
    assert service.record_receipt(payload, project_id="personal")["receipt_id"] == "bound-receipt"

    mismatched = manifest.model_copy(update={"spec_hash": "0" * 64})
    bad_receipt = create_receipt(mismatched, receipt_id="mismatched-receipt")
    with pytest.raises(EvidenceError) as mismatch:
        service.record_receipt(
            {"manifest": mismatched.model_dump(mode="json"), "receipt": bad_receipt.model_dump(mode="json"), "evidence_type": "fixture", "execution_id": execution_id},
            project_id="personal",
        )
    assert mismatch.value.code == "execution_binding_mismatch"

    with repository.transaction() as connection:
        connection.execute(executions.insert().values(
            id="legacy-execution", experiment_id="bound-experiment", status="legacy_local_unverified", parameters={},
        ))
    legacy_receipt = create_receipt(manifest, receipt_id="legacy-receipt")
    with pytest.raises(EvidenceError) as legacy:
        service.record_receipt(
            {"manifest": manifest.model_dump(mode="json"), "receipt": legacy_receipt.model_dump(mode="json"), "evidence_type": "fixture", "execution_id": "legacy-execution"},
            project_id="personal",
        )
    assert legacy.value.code == "execution_binding_mismatch"


def test_receipt_is_immutable_and_exact_replay_is_idempotent(evidence_service) -> None:
    service, repository, store = evidence_service
    first, manifest = _record(service, repository, store)
    receipt = create_receipt(manifest, receipt_id="receipt-one")
    replay = service.record_receipt(
        {"manifest": manifest.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"), "evidence_type": "fixture", "execution_id": None},
        project_id="personal",
    )
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True

    second_artifact = store.put_bytes(b"different evidence")
    repository.register_artifact(second_artifact, size_bytes=18, storage_uri=store.uri_for(second_artifact))
    conflict_manifest = _manifest(second_artifact)
    conflict_receipt = create_receipt(conflict_manifest, receipt_id="receipt-one")
    with pytest.raises(EvidenceError, match="already bound"):
        service.record_receipt(
            {"manifest": conflict_manifest.model_dump(mode="json"), "receipt": conflict_receipt.model_dump(mode="json"), "evidence_type": "fixture", "execution_id": None},
            project_id="personal",
        )


def test_verification_rereads_actual_artifacts_and_project_isolation(evidence_service) -> None:
    service, repository, store = evidence_service
    recorded, manifest = _record(service, repository, store)
    receipt_id = recorded["receipt_id"]
    assert service.verify_receipt(receipt_id, project_id="personal")["verified"] is True

    Path(store.uri_for(manifest.artifact_hashes[0])).unlink()
    failed = service.verify_receipt(receipt_id, project_id="personal")
    assert failed["verified"] is False
    assert "missing or unreadable artifact" in failed["errors"][0]
    with pytest.raises(EvidenceError) as hidden:
        service.get_receipt(receipt_id, project_id="other")
    assert hidden.value.code == "evidence_not_found"


def test_verification_rejects_db_artifact_mismatch(evidence_service) -> None:
    service, repository, store = evidence_service
    recorded, _ = _record(service, repository, store)
    replacement = store.put_bytes(b"replacement")
    repository.register_artifact(replacement, size_bytes=11, storage_uri=store.uri_for(replacement))
    with repository.transaction() as connection:
        connection.execute(delete(evidence_receipt_artifacts).where(
            evidence_receipt_artifacts.c.receipt_id == recorded["receipt_id"],
        ))
        connection.execute(insert(evidence_receipt_artifacts).values(
            receipt_id=recorded["receipt_id"], artifact_digest=replacement,
        ))
    failed = service.verify_receipt(recorded["receipt_id"], project_id="personal")
    assert failed["verified"] is False
    assert "absent from DB registry" in failed["errors"][0]


def test_reproduction_requires_separate_bound_receipts_and_cannot_self_assert_independence(evidence_service) -> None:
    service, repository, store = evidence_service
    original, original_manifest = _record(service, repository, store, receipt_id="original")
    reproduced, reproduced_manifest = _record(service, repository, store, receipt_id="reproduced")
    payload = {
        "receipt": {
            "receipt_id": "reproduction-one",
            "original_operator_id": "original-operator",
            "original_authority_id": "original-authority",
            "reproducer_operator_id": "reproducer-operator",
            "reproducer_authority_id": "reproducer-authority",
            "original_environment_hash": "4" * 64,
            "reproducer_environment_hash": "5" * 64,
            "original_manifest_hash": original_manifest and original["manifest_hash"],
            "reproduced_manifest_hash": reproduced_manifest and reproduced["manifest_hash"],
            "deviations": ["different host kernel"],
            "independent": True,
        },
        "original_evidence_receipt_id": "original",
        "reproduced_evidence_receipt_id": "reproduced",
        "external_attestation": None,
    }
    with pytest.raises(EvidenceError) as rejected:
        service.create_reproduction(payload, project_id="personal")
    assert rejected.value.code == "invalid_reproduction"

    payload["receipt"]["independent"] = False
    Path(store.uri_for(original_manifest.artifact_hashes[0])).unlink()
    with pytest.raises(EvidenceError) as source_unverified:
        service.create_reproduction(payload, project_id="personal")
    assert source_unverified.value.code == "reproduction_source_unverified"
    assert store.put_bytes(b"evidence") == original_manifest.artifact_hashes[0]
    created = service.create_reproduction(payload, project_id="personal")
    assert created["independently_verified"] is False
    assert created["external_attestation_contract"] == "missing"
    assert "no correctness" in created["claim_ceiling"]
    with repository.engine.connect() as connection:
        stored = connection.execute(reproductions.select()).mappings().one()
    assert stored["receipt_json"]["deviations"] == ["different host kernel"]


def test_derived_fixture_receipt_reloads_worker_and_evaluator_evidence(tmp_path: Path) -> None:
    from tests.services_v1.test_analysis_service import _service as analysis_fixture

    analysis, execution_id = analysis_fixture(tmp_path)
    _bind_evaluator_result_artifacts(analysis)
    service = EvidenceService(analysis.repository, analysis.artifact_store, personal_project_id="personal")
    first = service.derive_execution_receipt(
        {"execution_id": execution_id, "request_key": "derived-fixture"}, project_id="personal",
    )
    replay = service.derive_execution_receipt(
        {"execution_id": execution_id, "request_key": "derived-fixture"}, project_id="personal",
    )
    assert first["evidence_type"] == "derived_fixture"
    assert first["evidence_class"] == "fixture"
    assert first["admission_workflow"] == "derived_execution"
    assert replay["receipt_id"] == first["receipt_id"]
    assert replay["idempotent_replay"] is True
    with analysis.repository.engine.connect() as conn:
        evaluation_result_artifact = conn.execute(
            select(evaluations.c.result_artifact_digest)
        ).scalar_one()
    stored = analysis.repository.get_evidence_receipt("personal", first["receipt_id"])
    assert stored is not None
    assert evaluation_result_artifact in stored["artifact_hashes"]
    changed_result = {"changed": True}
    changed_bytes = canonical_json(changed_result)
    changed_digest = analysis.artifact_store.put_bytes(changed_bytes)
    analysis.repository.register_artifact(
        changed_digest, size_bytes=len(changed_bytes), storage_uri=analysis.artifact_store.uri_for(changed_digest),
    )
    with analysis.repository.transaction() as conn:
        conn.execute(update(evaluations).values(
            result=changed_result, result_hash=changed_digest, result_artifact_digest=changed_digest,
        ))
    with pytest.raises(EvidenceError) as changed_replay:
        service.derive_execution_receipt(
            {"execution_id": execution_id, "request_key": "derived-fixture"}, project_id="personal",
        )
    assert changed_replay.value.code == "derived_receipt_conflict"
    analysis.repository.create_project("Other", project_id="other")
    with pytest.raises(EvidenceError) as cross_project:
        service.derive_execution_receipt(
            {"execution_id": execution_id, "request_key": "cross-project"}, project_id="other",
        )
    assert cross_project.value.code == "execution_not_found"


def test_derived_receipt_holds_for_missing_evaluation_or_artifact(tmp_path: Path) -> None:
    from tests.services_v1.test_analysis_service import _service as analysis_fixture

    analysis, execution_id = analysis_fixture(tmp_path)
    service = EvidenceService(analysis.repository, analysis.artifact_store, personal_project_id="personal")
    with analysis.repository.transaction() as conn:
        conn.execute(delete(evaluations))
    with pytest.raises(EvidenceError) as missing_evaluation:
        service.derive_execution_receipt(
            {"execution_id": execution_id, "request_key": "missing-evaluation"}, project_id="personal",
        )
    assert missing_evaluation.value.code == "derived_evidence_hold"


def test_derived_receipt_rereads_evaluator_owned_result_artifact(tmp_path: Path) -> None:
    from tests.services_v1.test_analysis_service import _service as analysis_fixture

    analysis, execution_id = analysis_fixture(tmp_path)
    _bind_evaluator_result_artifacts(analysis)
    with analysis.repository.transaction() as conn:
        conn.execute(update(evaluations).values(result_hash="0" * 64))
    service = EvidenceService(analysis.repository, analysis.artifact_store, personal_project_id="personal")
    with pytest.raises(EvidenceError) as held:
        service.derive_execution_receipt(
            {"execution_id": execution_id, "request_key": "tampered-evaluator-result"}, project_id="personal",
        )
    assert held.value.code == "derived_evidence_hold"
    assert "evaluator result artifact does not match its result hash" in str(held.value)


def test_derived_receipt_holds_mixed_fixture_and_live_harnesses(tmp_path: Path) -> None:
    from tests.services_v1.test_analysis_service import _service as analysis_fixture

    analysis, execution_id = analysis_fixture(tmp_path)
    _bind_evaluator_result_artifacts(analysis)
    service = EvidenceService(analysis.repository, analysis.artifact_store, personal_project_id="personal")
    binding, rows, prices = analysis.repository.derived_execution_evidence_source("personal", execution_id)
    assert binding is not None and len(rows) == 1
    live = deepcopy(rows[0])
    live_job = next(job for job in live["jobs"] if job["kind"] == "attempt")
    live_harness = dict(live_job["payload"]["harness"])
    configuration = {"endpoint": "mixed-live-endpoint"}
    live_harness.update({
        "adapter": "http", "adapter_identity": "mixed-live", "adapter_digest": "8" * 64,
        "configuration": configuration, "effective_configuration_hash": sha256(configuration),
        "execution_mode": "remote", "isolation": "remote_sandbox", "claim_eligibility": "live_provider",
        "schema_hashes": {"input_hash": "4" * 64, "output_hash": "5" * 64, "trace_hash": "6" * 64, "config_schema_hash": "7" * 64},
    })
    live_job["payload"] = {**live_job["payload"], "harness": live_harness}
    with pytest.raises(EvidenceError) as held:
        service._derive_manifest("personal", binding, [rows[0], live], prices)
    assert held.value.code == "derived_evidence_hold"
    assert "mixes fixture-only and live harness attempts" in str(held.value)


def test_derived_receipt_holds_terminal_request_continuity_break(tmp_path: Path) -> None:
    from tests.services_v1.test_analysis_service import _service as analysis_fixture

    analysis, execution_id = analysis_fixture(tmp_path)
    _bind_evaluator_result_artifacts(analysis)
    service = EvidenceService(analysis.repository, analysis.artifact_store, personal_project_id="personal")
    binding, rows, prices = analysis.repository.derived_execution_evidence_source("personal", execution_id)
    assert binding is not None and len(rows) == 1
    tampered = deepcopy(rows[0])
    terminal = dict(tampered["result_metadata"]["terminal_envelope"])
    terminal["request_hash"] = "0" * 64
    tampered["result_metadata"] = {**tampered["result_metadata"], "terminal_envelope": terminal}
    with pytest.raises(EvidenceError) as held:
        service._derive_manifest("personal", binding, [tampered], prices)
    assert held.value.code == "derived_evidence_hold"
    assert "terminal envelope changes immutable request field request_hash" in str(held.value)


def test_derived_local_live_receipt_requires_service_persisted_live_gates(tmp_path: Path) -> None:
    from tests.services_v1.test_analysis_service import _service as analysis_fixture

    analysis, execution_id = analysis_fixture(tmp_path)
    _bind_evaluator_result_artifacts(analysis)
    with analysis.repository.transaction() as conn:
        attempt = conn.execute(select(attempts).limit(1)).mappings().one()
        job = conn.execute(
            select(jobs).where(
                jobs.c.attempt_id == attempt["id"], jobs.c.kind == "attempt"
            )
        ).mappings().one()
        request = dict(attempt["request_metadata"])
        envelope = dict(request["envelope"])
        endpoint_digest = "9" * 64
        envelope.update({"endpoint_id": "live-endpoint", "pinned_endpoint_digest": endpoint_digest})
        result = dict(attempt["result_metadata"])
        terminal = dict(result["terminal_envelope"])
        terminal.update({
            "endpoint_id": "live-endpoint", "pinned_endpoint_digest": endpoint_digest,
            "observed_endpoint_digest": endpoint_digest, "observed_provider_version": "provider-v1",
        })
        result.update({"terminal_envelope": terminal, "usage": {"input_tokens": 1, "output_tokens": 1}})
        payload = dict(job["payload"])
        harness = dict(payload["harness"])
        configuration = {"endpoint": "live-endpoint"}
        harness.update({
            "adapter": "http", "adapter_identity": "live-provider", "adapter_digest": "8" * 64,
            "configuration": configuration, "effective_configuration_hash": sha256(configuration),
            "execution_mode": "remote", "isolation": "remote_sandbox", "claim_eligibility": "live_provider",
            "schema_hashes": {"input_hash": "4" * 64, "output_hash": "5" * 64, "trace_hash": "6" * 64, "config_schema_hash": "7" * 64},
        })
        payload["harness"] = harness
        attempt_input = dict(payload["attempt_input"])
        attempt_input["attempt"] = envelope
        attempt_input["binding_digest"] = sha256({
            "scenario_id": attempt_input["scenario"]["scenario_id"],
            "scenario_digest": attempt_input["scenario_digest"],
            "attempt": envelope,
        })
        payload["attempt_input"] = attempt_input
        conn.execute(update(attempts).where(attempts.c.id == attempt["id"]).values(request_metadata={**request, "envelope": envelope}, result_metadata=result))
        conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(payload=payload))
    service = EvidenceService(analysis.repository, analysis.artifact_store, personal_project_id="personal")
    derived = service.derive_execution_receipt(
        {"execution_id": execution_id, "request_key": "derived-live"}, project_id="personal",
    )
    assert derived["evidence_type"] == "derived_local_live"
    assert derived["evidence_class"] == "local_live"
    row = analysis.repository.get_evidence_receipt("personal", derived["receipt_id"])
    assert row is not None
    assert "central_price_evidence_missing" in service._manifest(row).limitations
