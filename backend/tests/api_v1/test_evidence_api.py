from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.evidence import router
from artifacts_v1 import LocalArtifactStore
from evidence_v1 import EvidenceClass, EvidenceManifest, create_receipt
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from protocol_v1.models import LegacyEvidenceReceipt
from services_v1 import EvidenceService


def _client(tmp_path: Path) -> tuple[TestClient, EvidenceService, ArenaRepository, LocalArtifactStore]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    repository.create_project("Other", project_id="other")
    store = LocalArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    service = EvidenceService(repository, store, personal_project_id="personal")
    app.state.evidence_service = service
    app.include_router(router)
    return TestClient(app), service, repository, store


def _record(service: EvidenceService, repository: ArenaRepository, store: LocalArtifactStore, *, receipt_id: str = "api-receipt") -> str:
    artifact = store.put_bytes(b"api evidence")
    repository.register_artifact(artifact, size_bytes=12, storage_uri=store.uri_for(artifact))
    manifest = EvidenceManifest(
        experiment_id="private-experiment",
        experiment_hash="a" * 64, study_pack_hash="b" * 64, spec_hash="c" * 64, code_hash="d" * 64,
        runtime_hash="e" * 64, adapter_hash="f" * 64, model_hash="1" * 64, price_hash="2" * 64,
        evaluator_hashes=("3" * 64,), artifact_hashes=(artifact,), evidence_class=EvidenceClass.FIXTURE,
        claim_ceiling="fixture custody/integrity only; no correctness claim",
    )
    receipt = create_receipt(manifest, receipt_id=receipt_id)
    service.record_receipt(
        {"manifest": manifest.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"), "evidence_type": "fixture", "execution_id": None},
        project_id="personal",
    )
    return artifact


def test_evidence_api_is_redacted_project_scoped_and_truthful(tmp_path: Path) -> None:
    client, service, repository, store = _client(tmp_path)
    artifact = _record(service, repository, store)
    response = client.get("/api/v1/evidence/api-receipt")
    assert response.status_code == 200
    assert "private-experiment" not in response.text
    assert response.json()["artifacts"][0]["disposition"] == "withheld"
    assert response.json()["integrity_not_truth"] is True
    assert client.get("/api/v1/evidence/api-receipt", headers={"x-arena-project-id": "other"}).status_code == 404
    assert client.post("/api/v1/evidence/api-receipt/verify", json={"verified": True}).json()["verified"] is True
    Path(store.uri_for(artifact)).unlink()
    result = client.post("/api/v1/evidence/api-receipt/verify", json={"verified": True})
    assert result.status_code == 200
    assert result.json()["verified"] is False


def test_evidence_api_rejects_malformed_and_false_independence(tmp_path: Path) -> None:
    client, service, repository, store = _client(tmp_path)
    _record(service, repository, store)
    _record(service, repository, store, receipt_id="api-reproduced")
    assert client.post("/api/v1/reproductions", json=[]).status_code == 422
    original = client.get("/api/v1/evidence/api-receipt").json()
    reproduced = client.get("/api/v1/evidence/api-reproduced").json()
    payload = {
        "receipt": {
            "receipt_id": "repro",
            "original_operator_id": "original-operator",
            "original_authority_id": "original-authority",
            "reproducer_operator_id": "reproducer-operator",
            "reproducer_authority_id": "reproducer-authority",
            "original_environment_hash": "4" * 64,
            "reproducer_environment_hash": "5" * 64,
            "original_manifest_hash": original["manifest_hash"],
            "reproduced_manifest_hash": reproduced["manifest_hash"],
            "independent": True,
        },
        "original_evidence_receipt_id": "api-receipt",
        "reproduced_evidence_receipt_id": "api-reproduced",
        "external_attestation": None,
    }
    response = client.post("/api/v1/reproductions", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_generic_evidence_api_cannot_self_label_local_live(tmp_path: Path) -> None:
    client, _service, repository, store = _client(tmp_path)
    artifact = store.put_bytes(b"caller local live")
    repository.register_artifact(artifact, size_bytes=17, storage_uri=store.uri_for(artifact))
    manifest = EvidenceManifest(
        experiment_id="caller-labelled", experiment_hash="a" * 64, study_pack_hash="b" * 64,
        spec_hash="c" * 64, code_hash="d" * 64, runtime_hash="e" * 64,
        adapter_hash="f" * 64, model_hash="1" * 64, price_hash="2" * 64,
        evaluator_hashes=("3" * 64,), artifact_hashes=(artifact,), evidence_class=EvidenceClass.LOCAL_LIVE,
        claim_ceiling="local-live custody/integrity only; no correctness claim",
    )
    receipt = create_receipt(manifest, receipt_id="caller-local-live")
    response = client.post("/api/v1/evidence", json={
        "manifest": manifest.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"),
        "evidence_type": "local_live", "execution_id": None,
    })
    assert response.status_code == 409
    assert response.json()["verdict"] == "HOLD"
    assert response.json()["error"]["code"] == "evidence_admission_hold"


def test_evidence_api_accepts_canonical_receipt_and_rejects_legacy_shape(tmp_path: Path) -> None:
    client, _service, repository, store = _client(tmp_path)
    openapi = client.get("/openapi.json").json()
    assert openapi["paths"]["/api/v1/evidence"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/EvidenceAdmissionRequest")
    assert openapi["paths"]["/api/v1/reproductions"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/ReproductionRequest")
    artifact = store.put_bytes(b"canonical contract")
    repository.register_artifact(artifact, size_bytes=18, storage_uri=store.uri_for(artifact))
    manifest = EvidenceManifest(
        experiment_id="contract-experiment", experiment_hash="a" * 64, study_pack_hash="b" * 64,
        spec_hash="c" * 64, code_hash="d" * 64, runtime_hash="e" * 64,
        adapter_hash="f" * 64, model_hash="1" * 64, price_hash="2" * 64,
        evaluator_hashes=("3" * 64,), artifact_hashes=(artifact,), evidence_class=EvidenceClass.FIXTURE,
        claim_ceiling="fixture custody/integrity only; no correctness claim",
    )
    receipt = create_receipt(manifest, receipt_id="canonical-api-receipt")
    payload = {
        "manifest": manifest.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"),
        "evidence_type": "fixture", "execution_id": None,
    }
    assert client.post("/api/v1/evidence", json=payload).status_code == 200
    legacy = LegacyEvidenceReceipt(
        receipt_id="legacy-receipt", artifact_type="trace", artifact_hash="a" * 64,
        manifest_hash="a" * 64, environment_hash="b" * 64, evaluator_hashes=("c" * 64,),
        source_uri="file://legacy", created_at=datetime(2026, 8, 14, tzinfo=UTC),
        claim_ceiling="integrity only", limitations=(),
    )
    rejected = client.post("/api/v1/evidence", json={**payload, "receipt": legacy.model_dump(mode="json")})
    assert rejected.status_code == 422


def test_reproduction_api_rejects_legacy_reproduction_shape(tmp_path: Path) -> None:
    client, _service, _repository, _store = _client(tmp_path)
    legacy_receipt = {
        "protocol_version": "1.0", "receipt_id": "legacy-reproduction", "experiment_id": "experiment",
        "experiment_hash": "a" * 64, "study_pack_hash": "b" * 64, "manifest_hash": "c" * 64,
        "evaluator_hashes": ["d" * 64], "command": ["uv", "run"], "environment": {},
        "created_at": "2026-08-14T00:00:00Z", "limitations": [], "integrity_not_truth": True,
    }
    response = client.post("/api/v1/reproductions", json={
        "receipt": legacy_receipt, "original_evidence_receipt_id": "one",
        "reproduced_evidence_receipt_id": "two", "external_attestation": None,
    })
    assert response.status_code == 422


def test_evidence_list_is_scoped_paginated_redacted_and_read_only(tmp_path: Path) -> None:
    client, service, repository, store = _client(tmp_path)
    assert client.get("/api/v1/evidence").json()["evidence"] == []
    _record(service, repository, store, receipt_id="list-one")
    _record(service, repository, store, receipt_id="list-two")
    before = repository.get_evidence_receipt("personal", "list-one")
    page = client.get("/api/v1/evidence?kind=fixture&limit=1")
    assert page.status_code == 200
    body = page.json()
    assert body["pagination"]["next_offset"] == 1
    assert body["evidence"][0]["artifact_content"] == "withheld"
    assert "api evidence" not in page.text
    assert repository.get_evidence_receipt("personal", "list-one") == before
    assert client.get("/api/v1/evidence", headers={"x-arena-project-id": "other"}).json()["evidence"] == []
    assert client.get("/api/v1/evidence?limit=101").status_code == 400
    assert client.get("/api/v1/evidence?offset=-1").status_code == 400


def test_evidence_list_holds_on_missing_canonical_artifact(tmp_path: Path) -> None:
    client, service, repository, store = _client(tmp_path)
    artifact = _record(service, repository, store, receipt_id="list-corrupt")
    Path(store.uri_for(artifact)).unlink()
    result = client.get("/api/v1/evidence")
    assert result.status_code == 409
    assert result.json()["verdict"] == "HOLD"
