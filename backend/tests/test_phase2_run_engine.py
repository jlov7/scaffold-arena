from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator, Callable

import pytest

from config.settings import settings
from core import events as ev
from core.registry import register_scaffold, register_task
from core.run_engine import (
    RunEvictedError,
    RunKind,
    _run_single_scaffold,
    _runs,
    cancel_active_runs,
    create_run,
    get_run,
    start_arena_run,
    wait_for_run_completion,
)
from scaffolds.base import BaseScaffold
from tasks.base import BaseTask


class TimeoutTask(BaseTask):
    id = "timeout_test"
    name = "Timeout Test"
    subtitle = "Timeout test task"
    task_type = "extraction"
    synthetic_sources = False

    def get_input_text(self) -> str:
        return "timeout"

    def get_schema(self) -> dict:
        return {"type": "object"}

    def get_gold(self) -> dict:
        return {}


class SlowScaffold(BaseScaffold):
    id = "slow_scaffold"
    name = "Slow Scaffold"
    subtitle = "Sleeps to trigger timeout"

    async def run(
        self,
        run_id: str,
        task: BaseTask,
        model_id: str,
        provider: Any,
        options: Any,
        config_override: dict | None = None,
        cancelled_check: Callable[[], bool] | None = None,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        yield ("scaffold_phase", ev.scaffold_phase(run_id, self.id, "starting"))
        await asyncio.sleep(1.2)
        yield ("final_output", {"output": '{"ok": true}'})


@pytest.mark.asyncio
async def test_scaffold_timeout_emits_failed_result() -> None:
    register_task(TimeoutTask())
    register_scaffold(SlowScaffold())

    run = create_run(
        kind=RunKind.ARENA,
        task_id="timeout_test",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["slow_scaffold"],
        options={"timeout_s": 1},
    )
    await _run_single_scaffold(run, "slow_scaffold", provider=object())  # type: ignore[arg-type]

    assert "slow_scaffold" in run.results
    assert "timed out" in run.results["slow_scaffold"]["error"].lower()


def test_completed_runs_are_evicted_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "run_ttl_seconds", 1)

    run = create_run(
        kind=RunKind.ARENA,
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare"],
        options=None,
    )
    run._done = True
    run.completed_at = time.time() - 5

    with pytest.raises(RunEvictedError):
        get_run(run.run_id)


def test_active_runs_are_not_evicted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "run_ttl_seconds", 1)

    run = create_run(
        kind=RunKind.ARENA,
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare"],
        options=None,
    )
    run._done = False
    run.completed_at = time.time() - 5

    fetched = get_run(run.run_id)
    assert fetched.run_id == run.run_id
    _runs.pop(run.run_id, None)


@pytest.mark.asyncio
async def test_cancel_active_runs_and_wait_for_completion() -> None:
    _runs.clear()
    run = create_run(
        kind=RunKind.ARENA,
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare"],
        options=None,
    )
    run._done = False

    cancelled = cancel_active_runs()
    assert cancelled >= 1
    assert run.cancelled is True

    run._done = True
    done = await wait_for_run_completion(timeout_s=0.5)
    assert done is True
    _runs.clear()


@pytest.mark.asyncio
async def test_start_arena_run_handles_provider_init_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _runs.clear()
    run = create_run(
        kind=RunKind.ARENA,
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        scaffold_ids=["bare", "plan_execute_verify"],
        options=None,
    )

    def _boom(_: str, api_key_override: str | None = None) -> object:
        del api_key_override
        raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic models")

    monkeypatch.setattr("core.run_engine.get_provider", _boom)

    await start_arena_run(run)

    assert run._done is True
    assert run.completed_at is not None
    assert set(run.results.keys()) == {"bare", "plan_execute_verify"}
    assert run.results["bare"]["error"] == "ANTHROPIC_API_KEY is required for Anthropic models"
    assert run.results["plan_execute_verify"]["error"] == "ANTHROPIC_API_KEY is required for Anthropic models"

    event_types: list[str] = []
    while not run.queue.empty():
        event_type, _ = run.queue.get_nowait()
        event_types.append(event_type)

    assert event_types[0] == "run_started"
    assert event_types.count("scaffold_failed") == 2
    assert event_types[-1] == "run_complete"
