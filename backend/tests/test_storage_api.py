from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main as app_module
from core.storage import persist_run


@pytest.fixture
def client_with_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    db_path = tmp_path / "arena.db"
    monkeypatch.setattr(app_module.settings, "sqlite_path", str(db_path))
    with TestClient(app_module.app) as client:
        yield client


def test_sqlite_file_is_created_and_runs_endpoints_work(client_with_db: TestClient, tmp_path: Path) -> None:
    persist_run(
        run_id="run_test_1",
        kind="arena",
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare"],
        options={"temperature": 0},
        created_at=1.0,
        completed_at=2.0,
        winner_id="bare",
        status="completed",
        results={"bare": {"evaluation": {"total_score": 10}}},
    )

    db_path = tmp_path / "arena.db"
    assert db_path.exists()

    list_res = client_with_db.get("/api/runs")
    assert list_res.status_code == 200
    runs = list_res.json()["runs"]
    assert any(r["run_id"] == "run_test_1" for r in runs)

    detail_res = client_with_db.get("/api/runs/run_test_1")
    assert detail_res.status_code == 200
    assert detail_res.json()["run_id"] == "run_test_1"
    assert detail_res.json()["results"]["bare"]["evaluation"]["total_score"] == 10
