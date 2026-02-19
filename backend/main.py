from __future__ import annotations

import asyncio

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

load_dotenv()

from config.settings import settings  # noqa: E402
from config.models import all_models_meta  # noqa: E402
from core.registry import all_tasks_meta, all_scaffolds_meta  # noqa: E402
from core.run_engine import (  # noqa: E402
    RunKind,
    create_run,
    get_run,
    cancel_run,
    start_arena_run,
    start_patch_rerun,
    get_event_stream,
)

app = FastAPI(title="Scaffold Arena", version="0.1.0")

# CORS
origins = settings.cors_origins.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Register tasks and scaffolds on startup ---
@app.on_event("startup")
async def _register_all():
    from core.registry import register_task, register_scaffold
    from tasks.extraction import ExtractionTask
    from tasks.risk_analysis import RiskAnalysisTask
    from tasks.research_synthesis import ResearchSynthesisTask
    from scaffolds.bare import BareScaffold
    from scaffolds.plan_execute_verify import PlanExecuteVerifyScaffold
    from scaffolds.tool_error_recovery import ToolErrorRecoveryScaffold
    from scaffolds.memory_critique import MemoryCritiqueScaffold

    register_task(ExtractionTask())
    register_task(RiskAnalysisTask())
    register_task(ResearchSynthesisTask())

    register_scaffold(BareScaffold())
    register_scaffold(PlanExecuteVerifyScaffold())
    register_scaffold(ToolErrorRecoveryScaffold())
    register_scaffold(MemoryCritiqueScaffold())


# --- Health ---
@app.get("/api/health")
async def health():
    return {"status": "ok"}


# --- Meta ---
@app.get("/api/meta")
async def meta():
    return {
        "models": all_models_meta(),
        "tasks": all_tasks_meta(),
        "scaffolds": all_scaffolds_meta(),
        "features": {
            "llm_judge": settings.enable_llm_judge,
            "pdf_export": settings.enable_pdf_export,
        },
    }


# --- Arena runs ---
class CreateRunRequest(BaseModel):
    task_id: str
    model_id: str = "claude-sonnet-4-6"
    scaffold_ids: list[str] = [
        "bare",
        "plan_execute_verify",
        "tool_error_recovery",
        "memory_critique",
    ]
    options: dict | None = None


@app.post("/api/runs")
async def create_arena_run(req: CreateRunRequest):
    run = create_run(
        kind=RunKind.ARENA,
        task_id=req.task_id,
        model_id=req.model_id,
        scaffold_ids=req.scaffold_ids,
        options=req.options,
    )
    # Start in background — don't await
    asyncio.create_task(start_arena_run(run))
    return {
        "run_id": run.run_id,
        "stream_url": f"/api/runs/{run.run_id}/events",
        "cancel_url": f"/api/runs/{run.run_id}/cancel",
    }


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str):
    try:
        get_run(run_id)
    except ValueError:
        raise HTTPException(404, "Run not found")

    return EventSourceResponse(
        _sse_generator(run_id),
        media_type="text/event-stream",
    )


async def _sse_generator(run_id: str):
    """Wrap get_event_stream for EventSourceResponse (yields raw strings)."""
    async for frame in get_event_stream(run_id):
        yield frame


@app.post("/api/runs/{run_id}/cancel")
async def cancel(run_id: str):
    try:
        cancel_run(run_id)
    except ValueError:
        raise HTTPException(404, "Run not found")
    return {"status": "cancelled"}


# --- Proof comparison ---
class ComparisonRequest(BaseModel):
    task_id: str
    expensive_model_id: str = "claude-sonnet-4-6"
    cheap_model_id: str = "claude-haiku-4-5"
    winning_scaffold_id: str
    control_scaffold_id: str = "bare"
    options: dict | None = None


@app.post("/api/comparisons")
async def create_comparison(req: ComparisonRequest):
    from core.run_engine import _run_single_scaffold, RunState, RunOptions, _gen_run_id
    from core.provider import AnthropicProvider
    from core import events as ev

    run_id = _gen_run_id("cmp")
    opts = RunOptions(**(req.options or {}))
    queue: asyncio.Queue = asyncio.Queue()

    # Three cases
    cases = [
        {"case_id": "cheap_winning", "model_id": req.cheap_model_id, "scaffold_id": req.winning_scaffold_id},
        {"case_id": "expensive_bare", "model_id": req.expensive_model_id, "scaffold_id": req.control_scaffold_id},
        {"case_id": "expensive_winning", "model_id": req.expensive_model_id, "scaffold_id": req.winning_scaffold_id},
    ]

    async def _run_comparison():
        provider = AnthropicProvider()
        await queue.put(("comparison_started", ev.comparison_started(run_id, cases)))

        all_results = {}
        for case in cases:
            cid = case["case_id"]
            mid = case["model_id"]
            sid = case["scaffold_id"]

            # Create a temporary run state for this case
            case_run = RunState(
                run_id=run_id,
                kind=RunKind.COMPARISON,
                task_id=req.task_id,
                model_id=mid,
                scaffold_ids=[sid],
                options=opts,
                queue=asyncio.Queue(),  # separate queue, we'll forward
            )

            await queue.put(("case_started", ev.case_started(run_id, cid, mid, sid)))

            # Run the scaffold
            await _run_single_scaffold(case_run, sid, provider)

            # Forward events as case events
            result = case_run.results.get(sid, {})
            metrics = result.get("metrics", {})
            output = result.get("output", "")
            evaluation = result.get("evaluation", {})

            await queue.put(("case_completed", ev.case_completed(run_id, cid, output, metrics)))

            if evaluation:
                await queue.put((
                    "case_evaluation_completed",
                    ev.case_evaluation_completed(run_id, cid, evaluation.get("total_score", 0), evaluation.get("breakdown", {})),
                ))

            all_results[cid] = {"metrics": metrics, "evaluation": evaluation, "model_id": mid, "scaffold_id": sid}

        await queue.put(("comparison_complete", ev.comparison_complete(run_id, all_results)))

    asyncio.create_task(_run_comparison())

    # Store a minimal run for SSE streaming
    from core.run_engine import _runs
    run = RunState(
        run_id=run_id,
        kind=RunKind.COMPARISON,
        task_id=req.task_id,
        model_id=req.expensive_model_id,
        scaffold_ids=[req.winning_scaffold_id, req.control_scaffold_id],
        options=opts,
        queue=queue,
    )
    _runs[run_id] = run

    return {
        "run_id": run_id,
        "stream_url": f"/api/runs/{run_id}/events",
    }


# --- Autopsy ---
class AutopsyRequest(BaseModel):
    task_id: str
    scaffold_id: str
    output: str
    evaluation: dict
    metrics: dict | None = None


@app.post("/api/autopsy")
async def autopsy(req: AutopsyRequest):
    from autopsy.analyzer import analyze_failures

    result = await analyze_failures(
        task_id=req.task_id,
        scaffold_id=req.scaffold_id,
        output=req.output,
        evaluation=req.evaluation,
        metrics=req.metrics,
    )
    return result


# --- Patch rerun ---
class PatchRerunRequest(BaseModel):
    task_id: str
    model_id: str = "claude-sonnet-4-6"
    scaffold_id: str
    base_config: dict = {}
    patch: dict = {}


@app.post("/api/patch-reruns")
async def patch_rerun(req: PatchRerunRequest):
    merged_config = {**req.base_config, **req.patch}
    run = create_run(
        kind=RunKind.PATCH_RERUN,
        task_id=req.task_id,
        model_id=req.model_id,
        scaffold_ids=[req.scaffold_id],
        options=None,
    )
    asyncio.create_task(start_patch_rerun(run, config_override=merged_config))
    return {
        "run_id": run.run_id,
        "stream_url": f"/api/runs/{run.run_id}/events",
    }


# --- Report ---
class ReportRequest(BaseModel):
    task_id: str
    model_id: str
    results: dict
    comparison: dict | None = None
    autopsy: dict | None = None
    patch_rerun: dict | None = None


@app.post("/api/reports")
async def generate_report(req: ReportRequest):
    from report.markdown import generate_markdown

    md = generate_markdown(
        task_id=req.task_id,
        model_id=req.model_id,
        results=req.results,
        comparison=req.comparison,
        autopsy=req.autopsy,
        patch_rerun=req.patch_rerun,
    )

    response: dict = {"markdown": md}

    if settings.enable_pdf_export:
        try:
            from report.pdf import generate_pdf
            response["pdf_base64"] = generate_pdf(md)
        except ImportError:
            response["pdf_base64"] = None
    else:
        response["pdf_base64"] = None

    return response
