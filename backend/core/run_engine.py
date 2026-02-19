"""Run lifecycle management with fan-in event queue."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator

from core import events
from core.events import sse_event
from core.provider import AnthropicProvider
from core.registry import get_scaffold, get_task
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


# In-memory run store
_runs: dict[str, RunState] = {}


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
) -> RunState:
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
    )
    _runs[run_id] = run
    return run


def get_run(run_id: str) -> RunState:
    if run_id not in _runs:
        raise ValueError(f"Unknown run: {run_id}")
    return _runs[run_id]


def cancel_run(run_id: str) -> None:
    run = get_run(run_id)
    run.cancelled = True


async def _run_single_scaffold(
    run: RunState,
    scaffold_id: str,
    provider: AnthropicProvider,
    config_override: dict | None = None,
) -> None:
    """Execute a single scaffold and push events to the run queue."""
    task = get_task(run.task_id)
    scaffold = get_scaffold(scaffold_id)

    try:
        await run.queue.put(("scaffold_started", events.scaffold_started(run.run_id, scaffold_id)))

        start_time = time.time()
        total_input_tokens = 0
        total_output_tokens = 0
        num_api_calls = 0
        final_output = ""

        # Run the scaffold
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

            # Accumulate metrics from scaffold events
            if event_type == "usage":
                total_input_tokens += event_data.get("input_tokens", 0)
                total_output_tokens += event_data.get("output_tokens", 0)
                num_api_calls += 1
            elif event_type == "final_output":
                final_output = event_data.get("output", "")
            else:
                await run.queue.put((event_type, event_data))

        wall_time_ms = int((time.time() - start_time) * 1000)
        cost = cost_usd(total_input_tokens, total_output_tokens, run.model_id)

        metrics = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cost_usd": round(cost, 6),
            "wall_time_ms": wall_time_ms,
            "num_api_calls": num_api_calls,
        }

        await run.queue.put((
            "scaffold_completed",
            events.scaffold_completed(run.run_id, scaffold_id, final_output, metrics),
        ))

        # Run evaluation
        from evaluation.harness import evaluate

        eval_result = await evaluate(task, final_output, provider, run.model_id)

        await run.queue.put((
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
        ))

        run.results[scaffold_id] = {
            "output": final_output,
            "metrics": metrics,
            "evaluation": eval_result,
        }

    except Exception as e:
        await run.queue.put((
            "scaffold_failed",
            events.scaffold_failed(run.run_id, scaffold_id, str(e)),
        ))
        run.results[scaffold_id] = {"error": str(e)}


async def start_arena_run(run: RunState) -> None:
    """Launch scaffold tasks concurrently, then emit run_complete."""
    provider = AnthropicProvider()

    # Emit run_started
    await run.queue.put((
        "run_started",
        events.run_started(run.run_id, run.task_id, run.scaffold_ids),
    ))

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

    await run.queue.put((
        "run_complete",
        events.run_complete(run.run_id, winner_id, run.results),
    ))
    run._done = True


async def start_patch_rerun(
    run: RunState, config_override: dict | None = None
) -> None:
    """Run a single scaffold with patched config."""
    provider = AnthropicProvider()

    await run.queue.put((
        "run_started",
        events.run_started(run.run_id, run.task_id, run.scaffold_ids),
    ))

    await _run_single_scaffold(
        run, run.scaffold_ids[0], provider, config_override=config_override
    )

    winner_id = run.scaffold_ids[0] if run.results.get(run.scaffold_ids[0], {}).get("evaluation") else None

    await run.queue.put((
        "run_complete",
        events.run_complete(run.run_id, winner_id, run.results),
    ))
    run._done = True


async def get_event_stream(run_id: str) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE frames from the run queue."""
    run = get_run(run_id)
    last_heartbeat = time.time()

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
            last_heartbeat = time.time()
