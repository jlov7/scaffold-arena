from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.genome import router


def test_public_acp_lifecycle_routes_are_typed_nonexecuting_holds() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    cases = (
        ("get", "/api/v1/acp/registry"),
        ("post", "/api/v1/acp/certify"),
        ("post", "/api/v1/acp/runs"),
        ("post", "/api/v1/acp/runs/bridge-fixture/cancel"),
        ("get", "/api/v1/acp/runs/bridge-fixture/events"),
    )
    for method, path in cases:
        response = getattr(client, method)(path)
        assert response.status_code == 200
        payload = response.json()
        assert payload["verdict"] == "HOLD"
        assert payload["provider_execution_started"] is False


def test_acp_routes_reject_inline_identity_or_argv_admission() -> None:
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post("/api/v1/acp/runs", json={"argv": ["/bin/sh", "-c", "echo unsafe"]})
    assert response.json()["code"] == "acp_inline_admission_denied"
    assert response.json()["provider_execution_started"] is False
