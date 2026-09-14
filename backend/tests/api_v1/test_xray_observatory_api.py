from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.observatory import router as observatory_router
from api.v1.xray import router as xray_router
from tests.services_v1.test_xray_observatory_service import _observatory_service, _repository, _register, _xray_source
from services_v1 import XrayService


def test_xray_api_uses_only_captured_artifact_contract_and_returns_redacted_report(tmp_path) -> None:
    repository, store = _repository(tmp_path)
    source_digest = _register(repository, store, _xray_source())
    app = FastAPI()
    app.state.xray_service = XrayService(repository, store, personal_project_id="personal")
    app.include_router(xray_router)
    client = TestClient(app)

    created = client.post(
        "/api/v1/xray-analyses",
        json={"source_artifact_digest": source_digest, "source_kind": "sdk"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["execution_started"] is False
    assert body["network_requested"] is False
    assert "must-not-leak" not in created.text
    alias = client.get(f"/api/v1/xray/reports/{body['report_digest']}")
    assert alias.status_code == 200
    assert alias.json()["report_digest"] == body["report_digest"]
    rejected = client.post(
        "/api/v1/xray-analyses",
        json={
            "source_artifact_digest": source_digest,
            "source_kind": "sdk",
            "source_text": "caller supplied raw material is forbidden",
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "xray_request_invalid"


def test_observatory_api_preserves_report_and_legacy_ledger_route_without_partial_payloads(tmp_path) -> None:
    observatory, xray, _, source_digest = _observatory_service(tmp_path)
    xray_report = xray.create_report(
        {"source_artifact_digest": source_digest, "source_kind": "recorded_run"},
        project_id=None,
    )
    app = FastAPI()
    app.state.observatory_service = observatory
    app.include_router(observatory_router)
    client = TestClient(app)
    payload = {
        "attempt_ids": ["attempt-one"],
        "xray_analysis_digest": xray_report["report_digest"],
        "source_artifact_digest": source_digest,
        "diagnostic_partial_mode": False,
    }
    created = client.post("/api/v1/observatory-analyses", json=payload)
    assert created.status_code == 200
    body = created.json()
    assert body["fidelity_ladder"] == [
        "declared", "assigned", "available", "triggered", "applied", "activated", "observed", "downstream_pathway_detected"
    ]
    assert body["source_artifact_digest"] == f"sha256:{source_digest}"
    alias = client.get(f"/api/v1/observatory/reports/{body['report_digest']}")
    assert alias.status_code == 200
    assert alias.json()["report_digest"] == body["report_digest"]
    rejected = client.post("/api/v1/observatory-analyses", json={**payload, "events": []})
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "observatory_request_invalid"
    partial = client.post(
        "/api/v1/observatory/reports",
        json={**payload, "diagnostic_partial_mode": True},
    )
    assert partial.status_code == 400
    assert partial.json()["error"]["code"] == "observatory_request_invalid"
