from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import (
    extract_llm_api_key,
    limiter,
    validate_budget_for_new_run,
    validate_model_id,
    validate_scaffold_ids,
    validate_task_id,
)
from core import events as ev
from core.auth import verify_token
from core.provider import get_provider
from core.run_engine import RunKind, RunOptions, RunState, _run_single_scaffold, _runs
from core.run_lifecycle import gen_run_id
from core.storage import persist_run

router = APIRouter(tags=["comparisons"])


class ComparisonRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    expensive_model_id: str = Field(default="claude-sonnet-4-6", min_length=1, max_length=128)
    cheap_model_id: str = Field(default="claude-haiku-4-5", min_length=1, max_length=128)
    winning_scaffold_id: str = Field(min_length=1, max_length=128)
    control_scaffold_id: str = Field(default="bare", min_length=1, max_length=128)
    options: dict | None = None


class ModelComparisonRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    model_a_id: str = Field(min_length=1, max_length=128)
    model_b_id: str = Field(min_length=1, max_length=128)
    scaffold_id: str = Field(min_length=1, max_length=128)
    options: dict | None = None


def _validate_comparison_request(
    task_id: str, model_ids: list[str], scaffold_ids: list[str]
) -> None:
    validate_task_id(task_id)
    for model_id in model_ids:
        validate_model_id(model_id)
    validate_scaffold_ids(scaffold_ids)
    validate_budget_for_new_run()


async def _run_comparison_cases(
    *,
    run_id: str,
    task_id: str,
    cases: list[dict[str, str]],
    options: RunOptions,
    queue: asyncio.Queue,
    llm_api_key: str | None,
) -> dict:
    await queue.put(("comparison_started", ev.comparison_started(run_id, cases)))
    all_results: dict[str, dict] = {}
    for case in cases:
        case_id = case["case_id"]
        model_id = case["model_id"]
        scaffold_id = case["scaffold_id"]
        case_run = RunState(
            run_id=run_id,
            kind=RunKind.COMPARISON,
            task_id=task_id,
            model_id=model_id,
            scaffold_ids=[scaffold_id],
            options=options,
            queue=asyncio.Queue(),
        )
        await queue.put(("case_started", ev.case_started(run_id, case_id, model_id, scaffold_id)))
        provider = get_provider(model_id, api_key_override=llm_api_key)
        await _run_single_scaffold(case_run, scaffold_id, provider)
        result = case_run.results.get(scaffold_id, {})
        metrics = result.get("metrics", {})
        evaluation = result.get("evaluation", {})
        await queue.put(("case_completed", ev.case_completed(run_id, case_id, result.get("output", ""), metrics)))
        if evaluation:
            await queue.put((
                "case_evaluation_completed",
                ev.case_evaluation_completed(
                    run_id,
                    case_id,
                    evaluation.get("total_score", 0),
                    evaluation.get("breakdown", {}),
                ),
            ))
        all_results[case_id] = {
            "metrics": metrics,
            "evaluation": evaluation,
            "model_id": model_id,
            "scaffold_id": scaffold_id,
        }
    await queue.put(("comparison_complete", ev.comparison_complete(run_id, all_results)))
    return all_results


def _start_comparison(
    *,
    run_id: str,
    task_id: str,
    model_id: str,
    scaffold_ids: list[str],
    cases: list[dict[str, str]],
    options: RunOptions,
    llm_api_key: str | None,
    kind: str,
) -> None:
    queue: asyncio.Queue = asyncio.Queue()
    run = RunState(
        run_id=run_id,
        kind=RunKind.COMPARISON,
        task_id=task_id,
        model_id=model_id,
        scaffold_ids=scaffold_ids,
        options=options,
        queue=queue,
    )
    _runs[run_id] = run
    created_at = time.time()

    async def execute() -> None:
        all_results = await _run_comparison_cases(
            run_id=run_id,
            task_id=task_id,
            cases=cases,
            options=options,
            queue=queue,
            llm_api_key=llm_api_key,
        )
        winner_id = max(
            all_results,
            key=lambda case_id: all_results[case_id].get("evaluation", {}).get("total_score", 0),
        )
        completed_at = time.time()
        persist_run(
            run_id=run_id,
            kind=kind,
            task_id=task_id,
            model_id=model_id,
            scaffold_ids=scaffold_ids,
            options=options.__dict__,
            created_at=created_at,
            completed_at=completed_at,
            winner_id=winner_id,
            status="completed",
            results=all_results,
        )
        run._done = True
        run.completed_at = completed_at
        run.results = all_results

    asyncio.create_task(execute())


@router.post("/api/comparisons")
@limiter.limit("10/minute")
async def create_comparison(
    request: Request,
    req: ComparisonRequest,
    _auth: None = Depends(verify_token),
):
    _validate_comparison_request(
        req.task_id,
        [req.expensive_model_id, req.cheap_model_id],
        [req.winning_scaffold_id, req.control_scaffold_id],
    )
    try:
        options = RunOptions(**(req.options or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Run options are invalid.") from exc
    run_id = gen_run_id("cmp")
    cases = [
        {"case_id": "cheap_winning", "model_id": req.cheap_model_id, "scaffold_id": req.winning_scaffold_id},
        {"case_id": "expensive_bare", "model_id": req.expensive_model_id, "scaffold_id": req.control_scaffold_id},
        {"case_id": "expensive_winning", "model_id": req.expensive_model_id, "scaffold_id": req.winning_scaffold_id},
    ]
    _start_comparison(
        run_id=run_id, task_id=req.task_id, model_id=req.expensive_model_id,
        scaffold_ids=[req.winning_scaffold_id, req.control_scaffold_id], cases=cases,
        options=options, llm_api_key=extract_llm_api_key(request), kind=RunKind.COMPARISON.value,
    )
    return {"run_id": run_id, "stream_url": f"/api/runs/{run_id}/events"}


@router.post("/api/model-comparisons")
@limiter.limit("10/minute")
async def create_model_comparison(
    request: Request,
    req: ModelComparisonRequest,
    _auth: None = Depends(verify_token),
):
    _validate_comparison_request(req.task_id, [req.model_a_id, req.model_b_id], [req.scaffold_id])
    try:
        options = RunOptions(**(req.options or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Run options are invalid.") from exc
    run_id = gen_run_id("mcmp")
    cases = [
        {"case_id": "model_a", "model_id": req.model_a_id, "scaffold_id": req.scaffold_id},
        {"case_id": "model_b", "model_id": req.model_b_id, "scaffold_id": req.scaffold_id},
    ]
    _start_comparison(
        run_id=run_id, task_id=req.task_id, model_id=req.model_a_id,
        scaffold_ids=[req.scaffold_id], cases=cases, options=options,
        llm_api_key=extract_llm_api_key(request), kind="model_comparison",
    )
    return {"run_id": run_id, "stream_url": f"/api/runs/{run_id}/events"}
