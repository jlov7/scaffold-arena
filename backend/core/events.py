"""SSE event types and formatting helpers."""

from __future__ import annotations

import time
from typing import Any

import orjson


def ts_ms() -> int:
    return int(time.time() * 1000)


def sse_event(event_name: str, data: dict[str, Any], event_id: int) -> str:
    """Format a single SSE frame."""
    json_bytes = orjson.dumps(data)
    return f"id: {event_id}\nevent: {event_name}\ndata: {json_bytes.decode()}\n\n"


# --- Arena event builders ---


def run_started(run_id: str, task_id: str, scaffold_ids: list[str]) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "task_id": task_id,
        "scaffold_ids": scaffold_ids,
    }


def scaffold_started(run_id: str, scaffold_id: str) -> dict:
    return {"run_id": run_id, "ts_ms": ts_ms(), "scaffold_id": scaffold_id}


def scaffold_phase(run_id: str, scaffold_id: str, phase: str) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "scaffold_id": scaffold_id,
        "phase": phase,
    }


def scaffold_delta(run_id: str, scaffold_id: str, delta: str) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "scaffold_id": scaffold_id,
        "delta": delta,
    }


def scaffold_completed(
    run_id: str,
    scaffold_id: str,
    output: str,
    metrics: dict,
) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "scaffold_id": scaffold_id,
        "output": output,
        "metrics": metrics,
    }


def scaffold_failed(
    run_id: str, scaffold_id: str, error: str, retryable: bool = False
) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "scaffold_id": scaffold_id,
        "error": error,
        "retryable": retryable,
    }


def evaluation_completed(
    run_id: str,
    scaffold_id: str,
    total_score: float,
    breakdown: dict,
    weights: dict,
    notes: list[str],
    judge: dict | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "scaffold_id": scaffold_id,
        "total_score": total_score,
        "breakdown": breakdown,
        "weights": weights,
        "notes": notes,
        "judge": judge,
    }


def run_complete(
    run_id: str,
    winner_scaffold_id: str | None,
    results: dict,
) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "winner_scaffold_id": winner_scaffold_id,
        "results": results,
    }


def heartbeat(run_id: str) -> dict:
    return {"run_id": run_id, "ts_ms": ts_ms()}


# --- Comparison event builders ---


def comparison_started(run_id: str, cases: list[dict]) -> dict:
    return {"run_id": run_id, "ts_ms": ts_ms(), "cases": cases}


def case_started(run_id: str, case_id: str, model_id: str, scaffold_id: str) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "case_id": case_id,
        "model_id": model_id,
        "scaffold_id": scaffold_id,
    }


def case_delta(run_id: str, case_id: str, delta: str) -> dict:
    return {"run_id": run_id, "ts_ms": ts_ms(), "case_id": case_id, "delta": delta}


def case_completed(run_id: str, case_id: str, output: str, metrics: dict) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "case_id": case_id,
        "output": output,
        "metrics": metrics,
    }


def case_evaluation_completed(
    run_id: str,
    case_id: str,
    total_score: float,
    breakdown: dict,
) -> dict:
    return {
        "run_id": run_id,
        "ts_ms": ts_ms(),
        "case_id": case_id,
        "total_score": total_score,
        "breakdown": breakdown,
    }


def comparison_complete(run_id: str, results: dict) -> dict:
    return {"run_id": run_id, "ts_ms": ts_ms(), "results": results}
