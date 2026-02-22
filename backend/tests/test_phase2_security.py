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
    assert "budget" in body
    assert "daily_remaining_usd" in body["budget"]


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
    assert "Unknown task: does_not_exist" in bad_task.json()["detail"]

    bad_model = client.post(
        "/api/runs",
        json={"task_id": "extraction", "model_id": "bad-model", "scaffold_ids": ["bare"]},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert bad_model.status_code == 400
    assert "Unknown model: bad-model" in bad_model.json()["detail"]


def test_invalid_options_are_rejected_with_400(client: TestClient) -> None:
    res = client.post(
        "/api/runs",
        json={**_run_payload(), "options": {"timeout_s": 0}},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert res.status_code == 400
    assert "options.timeout_s" in res.json()["detail"]


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
