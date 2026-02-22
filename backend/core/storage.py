from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from config.settings import settings

_lock = Lock()


def _connect() -> sqlite3.Connection:
    db_path = Path(settings.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def init_db() -> None:
    with _lock:
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    scaffold_ids_json TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    completed_at REAL,
                    winner_id TEXT,
                    status TEXT NOT NULL,
                    results_json TEXT NOT NULL
                )
                """
            )
            conn.commit()


def persist_run(
    *,
    run_id: str,
    kind: str,
    task_id: str,
    model_id: str,
    scaffold_ids: list[str],
    options: dict[str, Any],
    created_at: float,
    completed_at: float | None,
    winner_id: str | None,
    status: str,
    results: dict[str, Any],
) -> None:
    with _lock:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id,
                    kind,
                    task_id,
                    model_id,
                    scaffold_ids_json,
                    options_json,
                    created_at,
                    completed_at,
                    winner_id,
                    status,
                    results_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    kind=excluded.kind,
                    task_id=excluded.task_id,
                    model_id=excluded.model_id,
                    scaffold_ids_json=excluded.scaffold_ids_json,
                    options_json=excluded.options_json,
                    created_at=excluded.created_at,
                    completed_at=excluded.completed_at,
                    winner_id=excluded.winner_id,
                    status=excluded.status,
                    results_json=excluded.results_json
                """,
                (
                    run_id,
                    kind,
                    task_id,
                    model_id,
                    json.dumps(scaffold_ids),
                    json.dumps(options),
                    created_at,
                    completed_at,
                    winner_id,
                    status,
                    json.dumps(results),
                ),
            )
            conn.commit()


def list_runs(limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    run_id,
                    kind,
                    task_id,
                    model_id,
                    created_at,
                    completed_at,
                    winner_id,
                    status,
                    results_json
                FROM runs
                ORDER BY COALESCE(completed_at, created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return [
        {
            "run_id": row[0],
            "kind": row[1],
            "task_id": row[2],
            "model_id": row[3],
            "created_at": row[4],
            "completed_at": row[5],
            "winner_id": row[6],
            "status": row[7],
            "results": json.loads(row[8]),
        }
        for row in rows
    ]


def get_run_record(run_id: str) -> dict[str, Any] | None:
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT
                    run_id,
                    kind,
                    task_id,
                    model_id,
                    scaffold_ids_json,
                    options_json,
                    created_at,
                    completed_at,
                    winner_id,
                    status,
                    results_json
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

    if row is None:
        return None

    return {
        "run_id": row[0],
        "kind": row[1],
        "task_id": row[2],
        "model_id": row[3],
        "scaffold_ids": json.loads(row[4]),
        "options": json.loads(row[5]),
        "created_at": row[6],
        "completed_at": row[7],
        "winner_id": row[8],
        "status": row[9],
        "results": json.loads(row[10]),
    }
