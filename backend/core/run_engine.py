"""Run lifecycle management with fan-in event queue."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from config.models import cost_usd
from core import events
from core.budget import budget_tracker, reset_current_run_id, set_current_run_id
from core.events import sse_event
from core.provider import LLMProvider, get_provider
from core.provider_errors import sanitize_provider_error, was_provider_error_sanitized
from core.registry import get_scaffold, get_task
from core.run_lifecycle import (
    RunEvictedError,
    RunKind,
    RunOptions,
    RunState,
    _runs,
    build_run_diagnostics,
    cancel_active_runs,
    cancel_run,
    create_run,
    event_summary,
    gen_run_id,
    get_run,
    wait_for_run_completion,
)
from core.storage import persist_run

logger = logging.getLogger(__name__)

__all__ = [
    "RunEvictedError",
    "RunKind",
    "RunOptions",
    "RunState",
    "_runs",
    "build_run_diagnostics",
    "cancel_active_runs",
    "cancel_run",
    "create_run",
    "gen_run_id",
    "get_run",
    "wait_for_run_completion",
]


async def _emit_run_event(run: RunState, event_type: str, event_data: dict[str, Any]) -> None:
    await run.queue.put((event_type, event_data))
    run.event_log.append(
        {
            "seq": len(run.event_log) + 1,
            "event": event_type,
            "ts_ms": int(event_data.get("ts_ms", events.ts_ms())),
            "scaffold_id": event_data.get("scaffold_id"),
            "summary": event_summary(event_type, event_data),
        }
    )


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
        except TimeoutError:
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
        error_msg = sanitize_provider_error(e)
        if was_provider_error_sanitized(e):
            logger.error(
                "scaffold_failed",
                extra={
                    "run_id": run.run_id,
                    "scaffold_id": scaffold_id,
                    "error": error_msg,
                },
            )
        else:
            logger.exception(
                "scaffold_failed",
                extra={"run_id": run.run_id, "scaffold_id": scaffold_id},
            )
        await _emit_run_event(
            run,
            "scaffold_failed",
            events.scaffold_failed(run.run_id, scaffold_id, error_msg),
        )
        run.results[scaffold_id] = {"error": error_msg}
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
        error_msg = sanitize_provider_error(e)
        if was_provider_error_sanitized(e):
            logger.error(
                "run_provider_init_failed",
                extra={"run_id": run.run_id, "error": error_msg},
            )
        else:
            logger.exception("run_provider_init_failed", extra={"run_id": run.run_id})
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
        error_msg = sanitize_provider_error(e)
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
        except TimeoutError:
            # Send heartbeat to keep connection alive
            run.event_counter += 1
            yield sse_event("heartbeat", events.heartbeat(run.run_id), run.event_counter)
