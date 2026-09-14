from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import main as app_module


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(app_module.settings, "api_secret_key", "test-secret")
    monkeypatch.setattr(app_module.settings, "daily_budget_usd", 50.0)
    monkeypatch.setattr(app_module.settings, "max_cost_per_run_usd", 2.0)

    async def _fake_start(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(app_module, "start_arena_run", _fake_start)
    monkeypatch.setattr(app_module, "start_patch_rerun", _fake_start)

    with TestClient(app_module.app) as test_client:
        yield test_client


def _run_payload() -> dict[str, Any]:
    return {
        "task_id": "extraction",
        "model_id": "claude-sonnet-4-6",
        "scaffold_ids": ["bare"],
    }


def test_get_endpoints_are_public(client: TestClient) -> None:
    res = client.get("/api/meta")
    assert res.status_code == 200
    body = res.json()
    assert body["build"]["git_sha"]
    assert body["limits"] == {"max_cost_per_run_usd": 2.0}
    assert "budget" not in body
    build = client.get("/api/build-meta")
    assert build.status_code == 200
    assert build.json()["app_version"] == "0.9.1"


def test_protected_endpoints_require_valid_bearer_token(client: TestClient) -> None:
    no_auth = client.post("/api/runs", json=_run_payload())
    assert no_auth.status_code == 401

    bad_auth = client.post(
        "/api/runs",
        json=_run_payload(),
        headers={"Authorization": "Bearer wrong"},
    )
    assert bad_auth.status_code == 401

    ok = client.post(
        "/api/runs",
        json=_run_payload(),
        headers={"Authorization": "Bearer test-secret"},
    )
    assert ok.status_code == 200
    assert "run_id" in ok.json()


def test_unknown_task_and_model_are_rejected_with_400(client: TestClient) -> None:
    bad_task = client.post(
        "/api/runs",
        json={"task_id": "does_not_exist", "model_id": "claude-sonnet-4-6", "scaffold_ids": ["bare"]},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert bad_task.status_code == 400
    assert bad_task.json()["detail"] == "Unknown task."

    bad_model = client.post(
        "/api/runs",
        json={"task_id": "extraction", "model_id": "bad-model", "scaffold_ids": ["bare"]},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert bad_model.status_code == 400
    assert bad_model.json()["detail"] == "Unknown model."


def test_invalid_options_are_rejected_with_400(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={**_run_payload(), "options": {"timeout_s": 0}},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Run options are invalid."


def test_preflight_provider_errors_never_expose_provider_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaked = "upstream path=/srv/keys request-header=Bearer token=sk-secret X-Key=abc"

    def _raise_provider(*args: Any, **kwargs: Any) -> object:
        raise RuntimeError(leaked)

    monkeypatch.setattr("core.provider.get_provider", _raise_provider)
    res = client.post("/api/preflight", json=_run_payload(), headers={"Authorization": "Bearer test-secret"})

    message = next(check["message"] for check in res.json()["checks"] if check["id"] == "provider")
    assert message == "Provider request could not be completed. Check provider settings and retry."
    for secret in ("/srv/keys", "Bearer", "sk-secret", "X-Key", "abc"):
        assert secret not in message


def test_request_size_limit_returns_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.settings, "max_request_size_bytes", 1024)
    payload = {
        "task_id": "extraction",
        "scaffold_id": "bare",
        "output": "x" * 5000,
        "evaluation": {"breakdown": {}},
    }
    res = client.post(
        "/api/autopsy",
        json=payload,
        headers={"Authorization": "Bearer test-secret"},
    )
    assert res.status_code == 413


def test_run_endpoint_rate_limits_with_retry_after(client: TestClient) -> None:
    headers = {"Authorization": "Bearer test-secret"}
    last_response = None
    for _ in range(6):
        last_response = client.post("/api/runs", json=_run_payload(), headers=headers)
    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


def test_security_headers_are_set_on_responses(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert res.headers["X-Permitted-Cross-Domain-Policies"] == "none"
    assert "camera=()" in res.headers["Permissions-Policy"]


def test_hsts_is_only_set_for_production_env(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev_response = client.get("/api/health")
    assert "Strict-Transport-Security" not in dev_response.headers

    monkeypatch.setattr(app_module.settings, "app_env", "production")
    prod_response = client.get("/api/health")
    assert prod_response.headers["Strict-Transport-Security"] == (
        "max-age=63072000; includeSubDomains; preload"
    )
