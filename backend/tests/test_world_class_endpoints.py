from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main as app_module
from core.storage import persist_run


def _auth_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer test-secret"}
    if extra:
        headers.update(extra)
    return headers


def _run_payload() -> dict[str, Any]:
    return {
        "task_id": "extraction",
        "model_id": "claude-sonnet-4-6",
        "scaffold_ids": ["bare"],
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    db_path = tmp_path / "arena.db"
    monkeypatch.setattr(app_module.settings, "sqlite_path", str(db_path))
    monkeypatch.setattr(app_module.settings, "api_secret_key", "test-secret")
    monkeypatch.setattr(app_module.settings, "daily_budget_usd", 50.0)
    monkeypatch.setattr(app_module.settings, "max_cost_per_run_usd", 2.0)
    app_module._idempotency_cache.clear()

    async def _fake_start(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(app_module, "start_arena_run", _fake_start)
    monkeypatch.setattr(app_module, "start_patch_rerun", _fake_start)
    with TestClient(app_module.app) as test_client:
        yield test_client


def test_preflight_reports_ready_state(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.provider.get_provider", lambda *args, **kwargs: object())
    res = client.post(
        "/api/preflight",
        json=_run_payload(),
        headers=_auth_headers(),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert all(check["status"] != "fail" for check in body["checks"])


def test_preflight_reports_provider_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_provider(*args: Any, **kwargs: Any) -> object:
        raise RuntimeError("Provider key missing")

    monkeypatch.setattr("core.provider.get_provider", _raise_provider)
    res = client.post(
        "/api/preflight",
        json=_run_payload(),
        headers=_auth_headers(),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    provider_check = next(check for check in body["checks"] if check["id"] == "provider")
    assert provider_check["status"] == "fail"
    assert "Provider key missing" in provider_check["message"]


def test_create_run_supports_idempotency_replay(client: TestClient) -> None:
    headers = _auth_headers({"X-Idempotency-Key": "demo-key-1"})
    first = client.post("/api/runs", json=_run_payload(), headers=headers)
    second = client.post("/api/runs", json=_run_payload(), headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert second_body["idempotent_replay"] is True
    assert first_body["run_id"] == second_body["run_id"]

    conflict = client.post(
        "/api/runs",
        json={**_run_payload(), "model_id": "claude-haiku-4-5"},
        headers=headers,
    )
    assert conflict.status_code == 409


def test_run_diagnostics_for_persisted_run(client: TestClient) -> None:
    persist_run(
        run_id="run_diag_1",
        kind="arena",
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare", "plan_execute_verify"],
        options={"temperature": 0},
        created_at=1.0,
        completed_at=2.0,
        winner_id="plan_execute_verify",
        status="completed",
        results={
            "bare": {"error": "failed"},
            "plan_execute_verify": {
                "output": "{\"foo\":\"bar\"}",
                "metrics": {"cost_usd": 0.01},
                "evaluation": {"total_score": 91.2},
            },
        },
    )

    res = client.get("/api/runs/run_diag_1/diagnostics")
    assert res.status_code == 200
    body = res.json()
    assert body["run_id"] == "run_diag_1"
    assert body["event_count"] >= 3
    assert len(body["timeline"]) >= 3
    assert body["scaffold_status"]["bare"] == "failed"


def test_export_bundle_contains_expected_files(client: TestClient) -> None:
    persist_run(
        run_id="run_export_1",
        kind="arena",
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare"],
        options={"temperature": 0},
        created_at=1.0,
        completed_at=2.0,
        winner_id="bare",
        status="completed",
        results={
            "bare": {
                "output": "{\"name\":\"Acme\"}",
                "metrics": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_usd": 0.01,
                    "wall_time_ms": 500,
                    "num_api_calls": 1,
                },
                "evaluation": {
                    "total_score": 88.8,
                    "breakdown": {"schema_validity": 100},
                    "weights": {"schema_validity": {"weight": 1.0, "type": "deterministic"}},
                    "notes": [],
                    "judge": None,
                },
            }
        },
    )

    res = client.get(
        "/api/runs/run_export_1/export-bundle",
        headers=_auth_headers(),
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/zip")

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = set(zf.namelist())
        assert {"README.txt", "run.json", "diagnostics.json", "report.md"}.issubset(names)
