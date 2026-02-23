"""Run lifecycle management with fan-in event queue."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator

from config.settings import settings
from core import events
from core.budget import budget_tracker, reset_current_run_id, set_current_run_id
from core.events import sse_event
from core.provider import LLMProvider, get_provider
from core.registry import get_scaffold, get_task
from core.storage import persist_run
from config.models import cost_usd


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


# In-memory run store
_runs: dict[str, RunState] = {}
_evicted_runs: set[str] = set()
logger = logging.getLogger(__name__)


def _evict_completed_runs() -> None:
    now = time.time()
    ttl = settings.run_ttl_seconds
    if ttl <= 0:
        return
    for run_id, run in list(_runs.items()):
        if not run._done or run.completed_at is None:
            continue
        if now - run.completed_at >= ttl:
            del _runs[run_id]
            _evicted_runs.add(run_id)


def _gen_run_id(prefix: str = "run") -> str:
    short = uuid.uuid4().hex[:8]
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}_{short}"


def create_run(
    kind: RunKind,
    task_id: str,
    model_id: str,
    scaffold_ids: list[str],
    options: dict | None = None,
    llm_api_key: str | None = None,
) -> RunState:
    _evict_completed_runs()
    opts = RunOptions(**(options or {}))
    prefix = {"arena": "run", "comparison": "cmp", "patch_rerun": "pr"}.get(
        kind.value, "run"
    )
    run_id = _gen_run_id(prefix)
    run = RunState(
        run_id=run_id,
        kind=kind,
        task_id=task_id,
        model_id=model_id,
        scaffold_ids=scaffold_ids,
        options=opts,
        llm_api_key=llm_api_key,
    )
    _runs[run_id] = run
    logger.info(
        "run_created",
        extra={
            "run_id": run_id,
            "kind": kind.value,
            "task_id": task_id,
            "model_id": model_id,
            "scaffold_ids": scaffold_ids,
        },
    )
    return run


def get_run(run_id: str) -> RunState:
    _evict_completed_runs()
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


def _event_summary(event_type: str, event_data: dict[str, Any]) -> str:
    scaffold_id = event_data.get("scaffold_id")
    if event_type == "run_started":
        return "Run started"
    if event_type == "run_complete":
        winner = event_data.get("winner_scaffold_id")
        return f"Run completed ({winner or 'no winner'})"
    if event_type == "scaffold_started":
        return f"{scaffold_id} started"
    if event_type == "scaffold_phase":
        return f"{scaffold_id} phase: {event_data.get('phase', 'unknown')}"
    if event_type == "scaffold_completed":
        return f"{scaffold_id} completed"
    if event_type == "scaffold_failed":
        return f"{scaffold_id} failed"
    if event_type == "evaluation_completed":
        score = event_data.get("total_score")
        return f"{scaffold_id} scored {score}"
    return event_type


async def _emit_run_event(run: RunState, event_type: str, event_data: dict[str, Any]) -> None:
    await run.queue.put((event_type, event_data))
    run.event_log.append(
        {
            "seq": len(run.event_log) + 1,
            "event": event_type,
            "ts_ms": int(event_data.get("ts_ms", events.ts_ms())),
            "scaffold_id": event_data.get("scaffold_id"),
            "summary": _event_summary(event_type, event_data),
        }
    )


def build_run_diagnostics(run: RunState) -> dict[str, Any]:
    status = "completed" if run._done else "running"
    if run._done and any("error" in result for result in run.results.values()):
        status = "failed"
    duration_ms = None
    if run.completed_at is not None:
        duration_ms = int((run.completed_at - run.created_at) * 1000)

    by_event = Counter(entry["event"] for entry in run.event_log)
    scaffold_status: dict[str, str] = {}
    errors: dict[str, str] = {}
    for scaffold_id in run.scaffold_ids:
        result = run.results.get(scaffold_id)
        if not result:
            scaffold_status[scaffold_id] = "pending"
            continue
        if "error" in result:
            scaffold_status[scaffold_id] = "failed"
            errors[scaffold_id] = str(result["error"])
            continue
        if "evaluation" in result:
            scaffold_status[scaffold_id] = "completed"
            continue
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
        "event_type_counts": dict(by_event),
        "scaffold_status": scaffold_status,
        "errors": errors,
        "timeline": run.event_log[-300:],
    }


async def _finalize_run(run: RunState, winner_id: str | None, status: str) -> None:
    await _emit_run_event(
        run,
        "run_complete",
        events.run_complete(run.run_id, winner_id, run.results),
    )
    run._done = True
    run.completed_at = time.time()
    budget_tracker.close_run(run.run_id)
    try:
        persist_run(
            run_id=run.run_id,
            kind=run.kind.value,
            task_id=run.task_id,
            model_id=run.model_id,
            scaffold_ids=run.scaffold_ids,
            options=run.options.__dict__,
            created_at=run.created_at,
            completed_at=run.completed_at,
            winner_id=winner_id,
            status=status,
            results=run.results,
        )
    except Exception:
        logger.exception("persist_run_failed", extra={"run_id": run.run_id})


async def _run_single_scaffold(
    run: RunState,
    scaffold_id: str,
    provider: LLMProvider,
    config_override: dict | None = None,
) -> None:
    """Execute a single scaffold and push events to the run queue."""
    task = get_task(run.task_id)
    scaffold = get_scaffold(scaffold_id)
    run_token = set_current_run_id(run.run_id)

    try:
        logger.info(
            "scaffold_started",
            extra={"run_id": run.run_id, "scaffold_id": scaffold_id},
        )
        await _emit_run_event(
            run, "scaffold_started", events.scaffold_started(run.run_id, scaffold_id)
        )

        async def _execute_scaffold() -> tuple[str, dict]:
            start_time = time.time()
            total_input_tokens = 0
            total_output_tokens = 0
            num_api_calls = 0
            final_output = ""

            async for event_type, event_data in scaffold.run(
                run_id=run.run_id,
                task=task,
                model_id=run.model_id,
                provider=provider,
                options=run.options,
                config_override=config_override,
                cancelled_check=lambda: run.cancelled,
            ):
                if run.cancelled:
                    break

                if event_type == "usage":
                    total_input_tokens += event_data.get("input_tokens", 0)
                    total_output_tokens += event_data.get("output_tokens", 0)
                    num_api_calls += 1
                elif event_type == "final_output":
                    final_output = event_data.get("output", "")
                else:
                    await _emit_run_event(run, event_type, event_data)

            wall_time_ms = int((time.time() - start_time) * 1000)
            cost = cost_usd(total_input_tokens, total_output_tokens, run.model_id)

            metrics = {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cost_usd": round(cost, 6),
                "wall_time_ms": wall_time_ms,
                "num_api_calls": num_api_calls,
            }
            return final_output, metrics

        try:
            final_output, metrics = await asyncio.wait_for(
                _execute_scaffold(),
                timeout=run.options.timeout_s,
            )
        except asyncio.TimeoutError:
            timeout_msg = f"Scaffold timed out after {run.options.timeout_s}s"
            logger.error(
                "scaffold_timeout",
                extra={
                    "run_id": run.run_id,
                    "scaffold_id": scaffold_id,
                    "timeout_s": run.options.timeout_s,
                },
            )
            await _emit_run_event(
                run,
                "scaffold_failed",
                events.scaffold_failed(run.run_id, scaffold_id, timeout_msg),
            )
            run.results[scaffold_id] = {"error": timeout_msg}
            return

        await _emit_run_event(
            run,
            "scaffold_completed",
            events.scaffold_completed(run.run_id, scaffold_id, final_output, metrics),
        )
        logger.info(
            "scaffold_completed",
            extra={"run_id": run.run_id, "scaffold_id": scaffold_id, **metrics},
        )

        # Run evaluation
        from evaluation.harness import evaluate

        eval_result = await evaluate(
            task,
            final_output,
            provider,
            run.model_id,
            evaluation_profile=run.options.evaluation_profile,
        )

        await _emit_run_event(
            run,
            "evaluation_completed",
            events.evaluation_completed(
                run.run_id,
                scaffold_id,
                eval_result["total_score"],
                eval_result["breakdown"],
                eval_result["weights"],
                eval_result["notes"],
                eval_result.get("judge"),
            ),
        )

        run.results[scaffold_id] = {
            "output": final_output,
            "metrics": metrics,
            "evaluation": eval_result,
        }

    except Exception as e:
        logger.exception(
            "scaffold_failed",
            extra={"run_id": run.run_id, "scaffold_id": scaffold_id},
        )
        await _emit_run_event(
            run,
            "scaffold_failed",
            events.scaffold_failed(run.run_id, scaffold_id, str(e)),
        )
        run.results[scaffold_id] = {"error": str(e)}
    finally:
        reset_current_run_id(run_token)


async def start_arena_run(run: RunState) -> None:
    """Launch scaffold tasks concurrently, then emit run_complete."""
    logger.info(
        "run_started",
        extra={"run_id": run.run_id, "kind": run.kind.value, "task_id": run.task_id},
    )

    # Emit run_started
    await _emit_run_event(
        run,
        "run_started",
        events.run_started(run.run_id, run.task_id, run.scaffold_ids),
    )

    try:
        provider = get_provider(run.model_id, api_key_override=run.llm_api_key)
    except Exception as e:
        logger.exception("run_provider_init_failed", extra={"run_id": run.run_id})
        error_msg = str(e)
        for sid in run.scaffold_ids:
            run.results[sid] = {"error": error_msg}
            await _emit_run_event(
                run,
                "scaffold_failed",
                events.scaffold_failed(run.run_id, sid, error_msg),
            )
        await _finalize_run(run, winner_id=None, status="failed")
        return

    # Launch all scaffolds concurrently
    tasks = []
    for sid in run.scaffold_ids:
        t = asyncio.create_task(_run_single_scaffold(run, sid, provider))
        tasks.append(t)

    run.active_tasks = len(tasks)
    await asyncio.gather(*tasks, return_exceptions=True)

    # Determine winner
    winner_id = None
    best_score = -1
    for sid, result in run.results.items():
        if "evaluation" in result:
            score = result["evaluation"]["total_score"]
            if score > best_score:
                best_score = score
                winner_id = sid

    await _finalize_run(run, winner_id=winner_id, status="completed")
    logger.info(
        "run_completed",
        extra={"run_id": run.run_id, "winner_id": winner_id, "scaffold_count": len(run.results)},
    )


async def start_patch_rerun(
    run: RunState, config_override: dict | None = None
) -> None:
    """Run a single scaffold with patched config."""
    await _emit_run_event(
        run,
        "run_started",
        events.run_started(run.run_id, run.task_id, run.scaffold_ids),
    )

    try:
        provider = get_provider(run.model_id, api_key_override=run.llm_api_key)
    except Exception as e:
        logger.exception("patch_rerun_provider_init_failed", extra={"run_id": run.run_id})
        scaffold_id = run.scaffold_ids[0]
        error_msg = str(e)
        run.results[scaffold_id] = {"error": error_msg}
        await _emit_run_event(
            run,
            "scaffold_failed",
            events.scaffold_failed(run.run_id, scaffold_id, error_msg),
        )
        await _finalize_run(run, winner_id=None, status="failed")
        return

    await _run_single_scaffold(
        run, run.scaffold_ids[0], provider, config_override=config_override
    )

    winner_id = run.scaffold_ids[0] if run.results.get(run.scaffold_ids[0], {}).get("evaluation") else None

    await _finalize_run(run, winner_id=winner_id, status="completed")
    logger.info("patch_rerun_completed", extra={"run_id": run.run_id, "winner_id": winner_id})


async def get_event_stream(run_id: str) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE frames from the run queue."""
    run = get_run(run_id)

    while True:
        try:
            event_type, event_data = await asyncio.wait_for(
                run.queue.get(), timeout=15.0
            )
            run.event_counter += 1
            yield sse_event(event_type, event_data, run.event_counter)

            if event_type in ("run_complete", "comparison_complete"):
                break
        except asyncio.TimeoutError:
            # Send heartbeat to keep connection alive
            run.event_counter += 1
            yield sse_event("heartbeat", events.heartbeat(run.run_id), run.event_counter)
