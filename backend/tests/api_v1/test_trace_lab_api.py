from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.trace_lab import router
from services_v1.trace_lab import TraceLabService


class _UnavailableRepository:
    pass


def test_trace_lab_api_requires_configured_service() -> None:
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post("/api/v1/trace-analyses", json={"left_attempt_id": "left", "right_attempt_id": "right"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "trace_lab_unavailable"


def test_trace_lab_api_rejects_non_object_and_raw_trace_material() -> None:
    app = FastAPI()
    app.state.trace_lab_service = TraceLabService(_UnavailableRepository())
    app.include_router(router)
    client = TestClient(app)
    assert client.post("/api/v1/trace-analyses", json=[]).status_code == 400
    response = client.post("/api/v1/trace-analyses", json={"left_attempt_id": "left", "right_attempt_id": "right", "outcome": {}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_trace_analysis_request"
