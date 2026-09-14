from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from api.v1.review import router
from persistence_v1.schema import annotation_batches
from tests.services_v1.test_review_service import _payload, _service


def test_annotation_batch_api_is_project_scoped_and_fail_closed(tmp_path) -> None:
    service, _, _ = _service(tmp_path)
    app = FastAPI()
    app.state.review_service = service
    app.include_router(router)
    client = TestClient(app)
    response = client.post("/api/v1/annotation-batches", json=_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"
    assignment = client.get("/api/v1/annotation-batches/batch-one?annotator_pseudonym=red").json()["assignments"][0]
    assert "score" not in str(assignment)
    detail = client.get(f"/api/v1/annotation-batches/batch-one/assignments/{assignment['assignment_id']}?annotator_pseudonym=red")
    assert detail.status_code == 200 and detail.json()["blinded_content"]["output"] == "reviewable response"
    assert client.post("/api/v1/annotation-batches/batch-one/annotations", json={
        "assignment_id": assignment["assignment_id"], "annotator_pseudonym": "red", "dimension_scores": {"quality": 0.8, "evidence": 0.8},
    }).json()["status"] == "IN_REVIEW"
    duplicate = _payload()
    duplicate["annotator_pseudonyms"] = ["red", "red", "green"]
    assert client.post("/api/v1/annotation-batches", json=duplicate).status_code == 422
    embedded = _payload()
    embedded["batch_id"] = "embedded"
    embedded["items"][0]["annotations"] = []
    assert client.post("/api/v1/annotation-batches", json=embedded).status_code == 422


def test_annotation_batch_api_accepts_public_contract_and_rejects_legacy_shape(tmp_path) -> None:
    service, _, _ = _service(tmp_path)
    app = FastAPI()
    app.state.review_service = service
    app.include_router(router)
    client = TestClient(app)
    openapi = client.get("/openapi.json").json()
    assert openapi["paths"]["/api/v1/annotation-batches"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/AnnotationBatch")
    assert openapi["paths"]["/api/v1/annotation-batches/{batch_id}/annotations"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/AnnotationSubmission")
    assert client.post("/api/v1/annotation-batches", json=_payload()).status_code == 200
    legacy = {
        "protocol_version": "1.0", "batch_id": "legacy-batch", "protocol_id": "legacy-protocol",
        "annotations": [], "created_at": "2026-08-14T00:00:00Z",
    }
    assert client.post("/api/v1/annotation-batches", json=legacy).status_code == 422


def test_annotation_batch_list_is_scoped_paginated_redacted_and_read_only(tmp_path) -> None:
    service, repository, _store = _service(tmp_path)
    app = FastAPI()
    app.state.review_service = service
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/v1/annotation-batches").json()["annotation_batches"] == []
    first = _payload()
    second = _payload()
    second["batch_id"] = "batch-two"
    assert client.post("/api/v1/annotation-batches", json=first).status_code == 200
    assert client.post("/api/v1/annotation-batches", json=second).status_code == 200
    before = repository.review_assignments("personal", "batch-one")
    page = client.get("/api/v1/annotation-batches?limit=1&offset=0")
    assert page.status_code == 200
    body = page.json()
    assert body["pagination"]["next_offset"] == 1
    assert body["annotation_batches"][0]["batch_id"] == "batch-one"
    assert "blinded_content" not in page.text and "blind_payload_digest" not in page.text
    assert repository.review_assignments("personal", "batch-one") == before
    assert client.get("/api/v1/annotation-batches", headers={"x-arena-project-id": "other"}).json()["annotation_batches"] == []
    assert client.get("/api/v1/annotation-batches?limit=0").status_code == 400
    assert client.get("/api/v1/annotation-batches?offset=-1").status_code == 400


def test_annotation_batch_list_holds_on_corrupt_stored_binding(tmp_path) -> None:
    service, repository, _store = _service(tmp_path)
    app = FastAPI()
    app.state.review_service = service
    app.include_router(router)
    client = TestClient(app)
    assert client.post("/api/v1/annotation-batches", json=_payload()).status_code == 200
    with repository.transaction() as conn:
        conn.execute(
            update(annotation_batches)
            .where(annotation_batches.c.id == "batch-one")
            .values(protocol_hash="0" * 64)
        )
    result = client.get("/api/v1/annotation-batches")
    assert result.status_code == 409
    assert result.json()["verdict"] == "HOLD"
