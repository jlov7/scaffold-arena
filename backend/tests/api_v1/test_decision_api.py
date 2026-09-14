from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from api.v1.decision import router
from persistence_v1.schema import decision_briefs
from tests.services_v1.test_decision_service import _decision_service, _request


def test_decision_api_returns_withheld_metadata_and_project_isolation(tmp_path) -> None:
    service, report = _decision_service(tmp_path)
    app = FastAPI()
    app.state.decision_service = service
    app.include_router(router)
    client = TestClient(app)
    response = client.post(
        "/api/v1/decision-briefs",
        headers={"x-arena-project-id": "personal"},
        json=_request(str(report["id"])),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["artifact_content"] == "withheld"
    assert "entries" not in body
    fetched = client.get(
        f"/api/v1/decision-briefs/{body['decision_brief_id']}",
        headers={"x-arena-project-id": "personal"},
    )
    assert fetched.status_code == 200
    isolated = client.get(
        f"/api/v1/decision-briefs/{body['decision_brief_id']}",
        headers={"x-arena-project-id": "other"},
    )
    assert isolated.status_code == 404


def test_decision_api_publishes_admission_contract_and_rejects_legacy_shape(tmp_path) -> None:
    service, report = _decision_service(tmp_path)
    app = FastAPI()
    app.state.decision_service = service
    app.include_router(router)
    client = TestClient(app)
    openapi = client.get("/openapi.json").json()
    schema = openapi["paths"]["/api/v1/decision-briefs"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/DecisionAdmissionRequest")
    canonical = _request(str(report["id"]))
    assert client.post("/api/v1/decision-briefs", json=canonical).status_code == 200
    by_execution = {
        **canonical,
        "experiment_id": str(report["experiment_id"]),
        "execution_id": str(report["execution_id"]),
    }
    del by_execution["analysis_report_id"]
    assert client.post("/api/v1/decision-briefs", json=by_execution).status_code == 200
    legacy = {
        "protocol_version": "1.0", "brief_id": "legacy-brief", "experiment_id": "experiment",
        "verdict": "hold", "outcome_summary": {}, "evidence_receipt_ids": [],
        "claim_ceiling": "integrity only", "next_action": "do nothing",
    }
    assert client.post("/api/v1/decision-briefs", json=legacy).status_code == 422


def test_decision_list_is_scoped_redacted_and_read_only(tmp_path) -> None:
    service, report = _decision_service(tmp_path)
    app = FastAPI()
    app.state.decision_service = service
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/v1/decision-briefs", headers={"x-arena-project-id": "personal"}).json()["decision_briefs"] == []
    created = client.post(
        "/api/v1/decision-briefs", headers={"x-arena-project-id": "personal"}, json=_request(str(report["id"])),
    ).json()
    before = service.repository.get_decision_brief("personal", created["decision_brief_id"])
    page = client.get("/api/v1/decision-briefs?limit=1", headers={"x-arena-project-id": "personal"})
    assert page.status_code == 200
    body = page.json()
    assert body["decision_briefs"][0]["decision_brief_id"] == created["decision_brief_id"]
    assert body["decision_briefs"][0]["artifact_content"] == "withheld"
    assert "entries" not in page.text
    assert service.repository.get_decision_brief("personal", created["decision_brief_id"]) == before
    assert client.get("/api/v1/decision-briefs", headers={"x-arena-project-id": "other"}).status_code == 404
    assert client.get("/api/v1/decision-briefs?limit=0", headers={"x-arena-project-id": "personal"}).status_code == 400
    assert client.get("/api/v1/decision-briefs?offset=-1", headers={"x-arena-project-id": "personal"}).status_code == 400


def test_decision_list_holds_on_corrupt_artifact_binding(tmp_path) -> None:
    service, report = _decision_service(tmp_path)
    app = FastAPI()
    app.state.decision_service = service
    app.include_router(router)
    client = TestClient(app)
    created = client.post(
        "/api/v1/decision-briefs", headers={"x-arena-project-id": "personal"}, json=_request(str(report["id"])),
    ).json()
    with service.repository.transaction() as conn:
        conn.execute(
            update(decision_briefs)
            .where(decision_briefs.c.id == created["decision_brief_id"])
            .values(verdict="HOLD")
        )
    result = client.get("/api/v1/decision-briefs", headers={"x-arena-project-id": "personal"})
    assert result.status_code == 409
    assert result.json()["verdict"] == "HOLD"
