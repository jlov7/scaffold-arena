from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main as app_module
from core.storage import persist_run


@pytest.fixture
def client_with_stats_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> TestClient:
    db_path = tmp_path / "arena_stats.db"
    monkeypatch.setattr(app_module.settings, "sqlite_path", str(db_path))
    with TestClient(app_module.app) as client:
        yield client


def _persist_arena_run(
    *,
    run_id: str,
    task_id: str,
    created_at: float,
    completed_at: float,
    winner_id: str,
    bare_score: float,
    pev_score: float,
) -> None:
    persist_run(
        run_id=run_id,
        kind="arena",
        task_id=task_id,
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare", "plan_execute_verify"],
        options={"temperature": 0},
        created_at=created_at,
        completed_at=completed_at,
        winner_id=winner_id,
        status="completed",
        results={
            "bare": {
                "evaluation": {"total_score": bare_score},
                "metrics": {"cost_usd": 0.01},
            },
            "plan_execute_verify": {
                "evaluation": {"total_score": pev_score},
                "metrics": {"cost_usd": 0.02},
            },
        },
    )


def test_stats_endpoint_returns_aggregates(client_with_stats_db: TestClient) -> None:
    _persist_arena_run(
        run_id="run_stats_1",
        task_id="extraction",
        created_at=1.0,
        completed_at=2.0,
        winner_id="bare",
        bare_score=90.0,
        pev_score=80.0,
    )
    _persist_arena_run(
        run_id="run_stats_2",
        task_id="extraction",
        created_at=3.0,
        completed_at=4.0,
        winner_id="plan_execute_verify",
        bare_score=70.0,
        pev_score=88.0,
    )
    _persist_arena_run(
        run_id="run_stats_3",
        task_id="risk",
        created_at=5.0,
        completed_at=6.0,
        winner_id="bare",
        bare_score=92.0,
        pev_score=75.0,
    )
    persist_run(
        run_id="cmp_ignored",
        kind="comparison",
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare"],
        options={},
        created_at=7.0,
        completed_at=8.0,
        winner_id="cheap_winning",
        status="completed",
        results={"cheap_winning": {"evaluation": {"total_score": 99.0}}},
    )

    response = client_with_stats_db.get("/api/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["run_count"] == 3
    assert len(data["scaffolds"]) == 2

    by_id = {row["scaffold_id"]: row for row in data["scaffolds"]}
    assert by_id["bare"]["wins"] == 2
    assert by_id["plan_execute_verify"]["wins"] == 1

    extraction_rows = {row["scaffold_id"]: row for row in data["by_task"]["extraction"]}
    assert extraction_rows["bare"]["avg_score"] == 80.0
    assert extraction_rows["plan_execute_verify"]["avg_score"] == 84.0

    bare_dist = next(
        dist for dist in data["distributions"] if dist["scaffold_id"] == "bare"
    )
    assert sum(bin_row["count"] for bin_row in bare_dist["bins"]) == by_id["bare"]["samples"]


def test_runs_list_is_sorted_most_recent_first(client_with_stats_db: TestClient) -> None:
    _persist_arena_run(
        run_id="run_old",
        task_id="extraction",
        created_at=10.0,
        completed_at=11.0,
        winner_id="bare",
        bare_score=60.0,
        pev_score=50.0,
    )
    _persist_arena_run(
        run_id="run_new",
        task_id="risk",
        created_at=20.0,
        completed_at=21.0,
        winner_id="plan_execute_verify",
        bare_score=65.0,
        pev_score=75.0,
    )

    response = client_with_stats_db.get("/api/runs")
    assert response.status_code == 200
    run_ids = [row["run_id"] for row in response.json()["runs"]]
    assert run_ids.index("run_new") < run_ids.index("run_old")
