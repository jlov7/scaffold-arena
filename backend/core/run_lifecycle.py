"""In-memory run state and lifecycle data helpers."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from config.settings import settings


class RunKind(str, Enum):
    ARENA = "arena"
    COMPARISON = "comparison"
    PATCH_RERUN = "patch_rerun"


@dataclass
class RunOptions:
    temperature: float = 0
    max_output_tokens: int = 2048
    timeout_s: int = 75
    evaluation_profile: str = "balanced"

    def __post_init__(self) -> None:
        if not 0 <= self.temperature <= 2:
            raise ValueError("options.temperature must be between 0.0 and 2.0")
        if not 1 <= self.max_output_tokens <= 32768:
            raise ValueError("options.max_output_tokens must be between 1 and 32768")
        if not 1 <= self.timeout_s <= 600:
            raise ValueError("options.timeout_s must be between 1 and 600")
        if self.evaluation_profile not in {"balanced", "strict", "cost_first"}:
            raise ValueError(
                "options.evaluation_profile must be one of: balanced, strict, cost_first"
            )


@dataclass
class RunState:
    run_id: str
    kind: RunKind
    task_id: str
    model_id: str
    scaffold_ids: list[str]
    options: RunOptions
    cancelled: bool = False
    created_at: float = field(default_factory=time.time)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    event_counter: int = 0
    results: dict[str, Any] = field(default_factory=dict)
    active_tasks: int = 0
    _done: bool = False
    completed_at: float | None = None
    llm_api_key: str | None = None
    event_log: list[dict[str, Any]] = field(default_factory=list)


class RunEvictedError(ValueError):
    pass


_runs: dict[str, RunState] = {}
_evicted_runs: set[str] = set()
logger = logging.getLogger(__name__)


def evict_completed_runs() -> None:
    now = time.time()
    ttl = settings.run_ttl_seconds
    if ttl <= 0:
        return
    for run_id, run in list(_runs.items()):
        if run._done and run.completed_at is not None and now - run.completed_at >= ttl:
            del _runs[run_id]
            _evicted_runs.add(run_id)


def gen_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def create_run(
    kind: RunKind,
    task_id: str,
    model_id: str,
    scaffold_ids: list[str],
    options: dict | None = None,
    llm_api_key: str | None = None,
) -> RunState:
    evict_completed_runs()
    opts = RunOptions(**(options or {}))
    prefix = {"arena": "run", "comparison": "cmp", "patch_rerun": "pr"}.get(
        kind.value, "run"
    )
    run = RunState(
        run_id=gen_run_id(prefix),
        kind=kind,
        task_id=task_id,
        model_id=model_id,
        scaffold_ids=scaffold_ids,
        options=opts,
        llm_api_key=llm_api_key,
    )
    _runs[run.run_id] = run
    logger.info(
        "run_created",
        extra={
            "run_id": run.run_id,
            "kind": kind.value,
            "task_id": task_id,
            "model_id": model_id,
            "scaffold_ids": scaffold_ids,
        },
    )
    return run


def get_run(run_id: str) -> RunState:
    evict_completed_runs()
    if run_id in _evicted_runs:
        raise RunEvictedError(f"Run evicted: {run_id}")
    if run_id not in _runs:
        raise ValueError(f"Unknown run: {run_id}")
    return _runs[run_id]


def cancel_run(run_id: str) -> None:
    run = get_run(run_id)
    run.cancelled = True
    logger.info("run_cancelled", extra={"run_id": run_id})


def cancel_active_runs() -> int:
    cancelled = 0
    for run in _runs.values():
        if not run._done and not run.cancelled:
            run.cancelled = True
            cancelled += 1
    return cancelled


async def wait_for_run_completion(timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if all(run._done for run in _runs.values()):
            return True
        await asyncio.sleep(0.1)
    return all(run._done for run in _runs.values())


def event_summary(event_type: str, event_data: dict[str, Any]) -> str:
    scaffold_id = event_data.get("scaffold_id")
    if event_type == "run_started":
        return "Run started"
    if event_type == "run_complete":
        return f"Run completed ({event_data.get('winner_scaffold_id') or 'no winner'})"
    if event_type == "scaffold_started":
        return f"{scaffold_id} started"
    if event_type == "scaffold_phase":
        return f"{scaffold_id} phase: {event_data.get('phase', 'unknown')}"
    if event_type == "scaffold_completed":
        return f"{scaffold_id} completed"
    if event_type == "scaffold_failed":
        return f"{scaffold_id} failed"
    if event_type == "evaluation_completed":
        return f"{scaffold_id} scored {event_data.get('total_score')}"
    return event_type


def build_run_diagnostics(run: RunState) -> dict[str, Any]:
    status = "completed" if run._done else "running"
    if run._done and any("error" in result for result in run.results.values()):
        status = "failed"
    duration_ms = (
        int((run.completed_at - run.created_at) * 1000)
        if run.completed_at is not None
        else None
    )
    event_counts = Counter(entry["event"] for entry in run.event_log)
    scaffold_status: dict[str, str] = {}
    errors: dict[str, str] = {}
    for scaffold_id in run.scaffold_ids:
        result = run.results.get(scaffold_id)
        if not result:
            scaffold_status[scaffold_id] = "pending"
        elif "error" in result:
            scaffold_status[scaffold_id] = "failed"
            errors[scaffold_id] = str(result["error"])
        elif "evaluation" in result:
            scaffold_status[scaffold_id] = "completed"
        else:
            scaffold_status[scaffold_id] = "running"

    return {
        "run_id": run.run_id,
        "kind": run.kind.value,
        "status": status,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "duration_ms": duration_ms,
        "task_id": run.task_id,
        "model_id": run.model_id,
        "scaffold_ids": run.scaffold_ids,
        "options": run.options.__dict__,
        "event_count": len(run.event_log),
        "event_type_counts": dict(event_counts),
        "scaffold_status": scaffold_status,
        "errors": errors,
        "timeline": run.event_log[-300:],
    }
