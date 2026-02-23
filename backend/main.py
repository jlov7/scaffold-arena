from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import time
import zipfile
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

load_dotenv()

from config.settings import settings  # noqa: E402
from config.models import all_models_meta  # noqa: E402
from core.auth import verify_token  # noqa: E402
from core.budget import DailyBudgetExceededError, budget_tracker  # noqa: E402
from core.logging_setup import setup_logging  # noqa: E402
from core.registry import all_tasks_meta, all_scaffolds_meta  # noqa: E402
from core.stats import compute_stats  # noqa: E402
from core.run_engine import (  # noqa: E402
    _runs,
    build_run_diagnostics,
    RunEvictedError,
    RunKind,
    cancel_active_runs,
    create_run,
    get_run,
    cancel_run,
    start_arena_run,
    start_patch_rerun,
    get_event_stream,
    wait_for_run_completion,
)
from core.storage import get_run_record, init_db, list_runs, persist_run  # noqa: E402

logger = logging.getLogger(__name__)
_IDEMPOTENCY_TTL_SECONDS = 60 * 60
_idempotency_cache: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    init_db()
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
    logger.info("startup_complete")
    try:
        yield
    finally:
        cancelled = cancel_active_runs()
        drained = await wait_for_run_completion(timeout_s=10.0)
        logger.info(
            "shutdown_complete",
            extra={"cancelled_runs": cancelled, "drained": drained},
        )


app = FastAPI(title="Scaffold Arena", version="0.1.0", lifespan=lifespan)
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    response = _rate_limit_exceeded_handler(request, exc)
    response.headers.setdefault("Retry-After", "60")
    return response

# CORS
origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-LLM-API-Key"],
)


def _is_production_env() -> bool:
    return settings.app_env.strip().lower() in {"prod", "production"}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if _is_production_env():
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=63072000; includeSubDomains; preload",
        )
    return response


@app.middleware("http")
async def enforce_request_size_limits(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_size_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body too large (> {settings.max_request_size_bytes} bytes)"},
                    )
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid Content-Length header")

        body = await request.body()
        if len(body) > settings.max_request_size_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large (> {settings.max_request_size_bytes} bytes)"},
            )

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)

    return await call_next(request)


def _extract_llm_api_key(request: Request) -> str | None:
    raw = request.headers.get("x-llm-api-key")
    if raw and raw.strip():
        return raw.strip()
    return None


def _available_task_ids() -> list[str]:
    return sorted(t["id"] for t in all_tasks_meta())


def _available_model_ids() -> list[str]:
    return sorted(m["id"] for m in all_models_meta())


def _available_scaffold_ids() -> list[str]:
    return sorted(s["id"] for s in all_scaffolds_meta())


def _validate_task_id(task_id: str) -> None:
    if task_id not in _available_task_ids():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task: {task_id}. Available: {_available_task_ids()}",
        )


def _validate_model_id(model_id: str) -> None:
    if model_id not in _available_model_ids():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {model_id}. Available: {_available_model_ids()}",
        )


def _validate_scaffold_ids(scaffold_ids: list[str]) -> None:
    valid = set(_available_scaffold_ids())
    for scaffold_id in scaffold_ids:
        if scaffold_id not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown scaffold: {scaffold_id}. Available: {_available_scaffold_ids()}",
            )


def _validate_budget_for_new_run() -> None:
    try:
        budget_tracker.check_new_run_allowed(daily_budget_usd=settings.daily_budget_usd)
    except DailyBudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


def _prune_idempotency_cache() -> None:
    now = time.time()
    for key, entry in list(_idempotency_cache.items()):
        if now - float(entry.get("ts", 0)) >= _IDEMPOTENCY_TTL_SECONDS:
            _idempotency_cache.pop(key, None)


def _idempotency_fingerprint(payload: dict, llm_api_key: str | None) -> str:
    normalized = {"payload": payload, "llm_api_key_present": bool(llm_api_key)}
    as_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(as_json.encode("utf-8")).hexdigest()


def _lookup_idempotent_response(idempotency_key: str, fingerprint: str) -> dict | None:
    _prune_idempotency_cache()
    cached = _idempotency_cache.get(idempotency_key)
    if not cached:
        return None
    if cached.get("fingerprint") != fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was reused with a different request payload.",
        )
    response = dict(cached.get("response", {}))
    response["idempotent_replay"] = True
    return response


def _store_idempotent_response(
    idempotency_key: str,
    fingerprint: str,
    response_payload: dict,
) -> None:
    _idempotency_cache[idempotency_key] = {
        "fingerprint": fingerprint,
        "response": dict(response_payload),
        "ts": time.time(),
    }


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
            "evaluation_profiles": ["balanced", "strict", "cost_first"],
        },
        "budget": {
            **budget_tracker.snapshot(daily_budget_usd=settings.daily_budget_usd),
            "max_cost_per_run_usd": settings.max_cost_per_run_usd,
        },
    }


def _live_run_payload(run) -> dict:  # noqa: ANN001
    return {
        "run_id": run.run_id,
        "kind": run.kind.value,
        "task_id": run.task_id,
        "model_id": run.model_id,
        "scaffold_ids": run.scaffold_ids,
        "options": run.options.__dict__,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "status": "completed" if run._done else "running",
        "results": run.results,
    }


# --- Arena runs ---
class CreateRunRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(default="claude-sonnet-4-6", min_length=1, max_length=128)
    scaffold_ids: list[str] = Field(
        default_factory=lambda: [
            "bare",
            "plan_execute_verify",
            "tool_error_recovery",
            "memory_critique",
        ]
    )
    options: dict | None = None
    custom_task: dict | None = None


class RunPreflightRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    scaffold_ids: list[str] = Field(min_length=1)
    options: dict | None = None


def _build_preflight_check(
    check_id: str,
    status: str,
    message: str,
    action: str | None = None,
) -> dict:
    payload = {"id": check_id, "status": status, "message": message}
    if action:
        payload["action"] = action
    return payload


@app.post("/api/preflight")
@limiter.limit("20/minute")
async def run_preflight(
    request: Request,
    req: RunPreflightRequest,
    _auth: None = Depends(verify_token),
):
    checks: list[dict] = []

    try:
        _validate_task_id(req.task_id)
        checks.append(_build_preflight_check("task", "pass", "Task is valid."))
    except HTTPException as exc:
        checks.append(
            _build_preflight_check(
                "task",
                "fail",
                str(exc.detail),
                "Select a task listed in the Task selector.",
            )
        )

    try:
        _validate_model_id(req.model_id)
        checks.append(_build_preflight_check("model", "pass", "Model is valid."))
    except HTTPException as exc:
        checks.append(
            _build_preflight_check(
                "model",
                "fail",
                str(exc.detail),
                "Choose a model from the current model registry.",
            )
        )

    try:
        _validate_scaffold_ids(req.scaffold_ids)
        checks.append(_build_preflight_check("scaffolds", "pass", "Scaffold selection is valid."))
    except HTTPException as exc:
        checks.append(
            _build_preflight_check(
                "scaffolds",
                "fail",
                str(exc.detail),
                "Adjust scaffold selection before running.",
            )
        )

    try:
        from core.run_engine import RunOptions

        RunOptions(**(req.options or {}))
        checks.append(_build_preflight_check("options", "pass", "Run options are valid."))
    except ValueError as exc:
        checks.append(
            _build_preflight_check(
                "options",
                "fail",
                str(exc),
                "Fix run options in Settings before starting.",
            )
        )

    try:
        _validate_budget_for_new_run()
        checks.append(_build_preflight_check("budget", "pass", "Budget allows a new run."))
    except HTTPException as exc:
        checks.append(
            _build_preflight_check(
                "budget",
                "fail",
                str(exc.detail),
                "Increase budget or wait for next daily rollover.",
            )
        )

    llm_api_key = _extract_llm_api_key(request)
    try:
        from core.provider import get_provider

        get_provider(req.model_id, api_key_override=llm_api_key)
        checks.append(_build_preflight_check("provider", "pass", "Provider credentials are ready."))
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        checks.append(
            _build_preflight_check(
                "provider",
                "fail",
                str(exc),
                "Set a valid provider key in Settings (BYOK) or backend environment.",
            )
        )

    ok = all(check["status"] != "fail" for check in checks)
    return {
        "ok": ok,
        "can_run": ok,
        "checked_at": time.time(),
        "checks": checks,
    }


@app.get("/api/runs")
async def get_runs(limit: int = 50):
    clamped_limit = max(1, min(limit, 500))
    stored = list_runs(limit=clamped_limit)
    live = []
    for run in list(_runs.values()):
        if not run._done:
            live.append(_live_run_payload(run))
    combined = live + stored
    combined.sort(
        key=lambda run: float(run.get("completed_at") or run.get("created_at") or 0),
        reverse=True,
    )
    return {"runs": combined}


@app.get("/api/stats")
async def get_stats(limit: int = 1000):
    return compute_stats(limit=limit)


@app.post("/api/runs")
@limiter.limit("5/minute")
async def create_arena_run(
    request: Request,
    req: CreateRunRequest,
    _auth: None = Depends(verify_token),
):
    llm_api_key = _extract_llm_api_key(request)
    idempotency_key_raw = request.headers.get("x-idempotency-key")
    idempotency_key = idempotency_key_raw.strip() if idempotency_key_raw else ""
    if idempotency_key:
        fingerprint = _idempotency_fingerprint(req.model_dump(mode="json"), llm_api_key)
        cached_response = _lookup_idempotent_response(idempotency_key, fingerprint)
        if cached_response is not None:
            return cached_response

    _validate_model_id(req.model_id)
    _validate_scaffold_ids(req.scaffold_ids)
    _validate_budget_for_new_run()

    task_id = req.task_id
    if req.custom_task:
        from core.registry import register_task
        from tasks.custom import CustomPromptTask

        custom_name = str(req.custom_task.get("name", "Custom Task"))
        custom_prompt = str(req.custom_task.get("prompt", "")).strip()
        custom_schema = req.custom_task.get("schema")
        if not custom_prompt:
            raise HTTPException(status_code=400, detail="custom_task.prompt is required")

        task_id = f"custom_{int(time.time() * 1000)}"
        register_task(
            CustomPromptTask(
                task_id=task_id,
                name=custom_name,
                prompt=custom_prompt,
                schema=custom_schema if isinstance(custom_schema, dict) else None,
            )
        )
    else:
        _validate_task_id(req.task_id)

    try:
        run = create_run(
            kind=RunKind.ARENA,
            task_id=task_id,
            model_id=req.model_id,
            scaffold_ids=req.scaffold_ids,
            options=req.options,
            llm_api_key=llm_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Start in background — don't await
    asyncio.create_task(start_arena_run(run))
    response_payload = {
        "run_id": run.run_id,
        "stream_url": f"/api/runs/{run.run_id}/events",
        "cancel_url": f"/api/runs/{run.run_id}/cancel",
        "idempotent_replay": False,
    }
    if idempotency_key:
        _store_idempotent_response(idempotency_key, fingerprint, response_payload)
    return response_payload


@app.get("/api/runs/{run_id}")
async def get_run_details(run_id: str):
    try:
        run = get_run(run_id)
        return _live_run_payload(run)
    except (RunEvictedError, ValueError):
        record = get_run_record(run_id)
        if record:
            return record
        raise HTTPException(404, "Run not found")


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str):
    try:
        get_run(run_id)
    except RunEvictedError:
        raise HTTPException(410, "Run has been evicted")
    except ValueError:
        raise HTTPException(404, "Run not found")

    return EventSourceResponse(
        _sse_generator(run_id),
        media_type="text/event-stream",
    )


def _build_stored_run_diagnostics(record: dict) -> dict:
    timeline: list[dict] = []
    seq = 1
    created_ts_ms = int(float(record.get("created_at") or time.time()) * 1000)
    timeline.append(
        {
            "seq": seq,
            "event": "run_started",
            "ts_ms": created_ts_ms,
            "scaffold_id": None,
            "summary": "Run started",
        }
    )
    seq += 1

    results = record.get("results") or {}
    event_counts: dict[str, int] = {"run_started": 1, "run_complete": 1}
    scaffold_status: dict[str, str] = {}
    errors: dict[str, str] = {}

    for scaffold_id, result in results.items():
        has_error = isinstance(result, dict) and "error" in result
        event = "scaffold_failed" if has_error else "scaffold_completed"
        event_counts[event] = event_counts.get(event, 0) + 1
        status = "failed" if has_error else "completed"
        scaffold_status[scaffold_id] = status
        if has_error:
            errors[scaffold_id] = str(result.get("error"))
        timeline.append(
            {
                "seq": seq,
                "event": event,
                "ts_ms": created_ts_ms + seq * 5,
                "scaffold_id": scaffold_id,
                "summary": f"{scaffold_id} {status}",
            }
        )
        seq += 1
        if not has_error and isinstance(result, dict) and result.get("evaluation"):
            event_counts["evaluation_completed"] = event_counts.get("evaluation_completed", 0) + 1
            timeline.append(
                {
                    "seq": seq,
                    "event": "evaluation_completed",
                    "ts_ms": created_ts_ms + seq * 5,
                    "scaffold_id": scaffold_id,
                    "summary": f"{scaffold_id} scored",
                }
            )
            seq += 1

    complete_ts_ms = int(float(record.get("completed_at") or record.get("created_at") or time.time()) * 1000)
    timeline.append(
        {
            "seq": seq,
            "event": "run_complete",
            "ts_ms": complete_ts_ms,
            "scaffold_id": None,
            "summary": "Run completed",
        }
    )

    duration_ms = None
    if record.get("completed_at") and record.get("created_at"):
        duration_ms = int((float(record["completed_at"]) - float(record["created_at"])) * 1000)

    return {
        "run_id": record.get("run_id"),
        "kind": record.get("kind"),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "completed_at": record.get("completed_at"),
        "duration_ms": duration_ms,
        "task_id": record.get("task_id"),
        "model_id": record.get("model_id"),
        "scaffold_ids": record.get("scaffold_ids", []),
        "options": record.get("options", {}),
        "event_count": len(timeline),
        "event_type_counts": event_counts,
        "scaffold_status": scaffold_status,
        "errors": errors,
        "timeline": timeline,
    }


def _resolve_run_payload(run_id: str) -> dict:
    try:
        run = get_run(run_id)
        payload = _live_run_payload(run)
        payload["diagnostics"] = build_run_diagnostics(run)
        return payload
    except (RunEvictedError, ValueError):
        record = get_run_record(run_id)
        if not record:
            raise HTTPException(404, "Run not found")
        payload = dict(record)
        payload["diagnostics"] = _build_stored_run_diagnostics(record)
        return payload


@app.get("/api/runs/{run_id}/diagnostics")
async def get_run_diagnostics(run_id: str):
    payload = _resolve_run_payload(run_id)
    return payload["diagnostics"]


async def _sse_generator(run_id: str):
    """Wrap get_event_stream for EventSourceResponse (yields raw strings)."""
    async for frame in get_event_stream(run_id):
        yield frame


@app.post("/api/runs/{run_id}/cancel")
@limiter.limit("10/minute")
async def cancel(
    request: Request,
    run_id: str,
    _auth: None = Depends(verify_token),
):
    try:
        cancel_run(run_id)
    except RunEvictedError:
        raise HTTPException(410, "Run has been evicted")
    except ValueError:
        raise HTTPException(404, "Run not found")
    return {"status": "cancelled"}


# --- Proof comparison ---
class ComparisonRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    expensive_model_id: str = Field(default="claude-sonnet-4-6", min_length=1, max_length=128)
    cheap_model_id: str = Field(default="claude-haiku-4-5", min_length=1, max_length=128)
    winning_scaffold_id: str = Field(min_length=1, max_length=128)
    control_scaffold_id: str = Field(default="bare", min_length=1, max_length=128)
    options: dict | None = None


@app.post("/api/comparisons")
@limiter.limit("10/minute")
async def create_comparison(
    request: Request,
    req: ComparisonRequest,
    _auth: None = Depends(verify_token),
):
    from core.run_engine import _run_single_scaffold, RunState, RunOptions, _gen_run_id
    from core.provider import get_provider
    from core import events as ev

    _validate_task_id(req.task_id)
    _validate_model_id(req.expensive_model_id)
    _validate_model_id(req.cheap_model_id)
    _validate_scaffold_ids([req.winning_scaffold_id, req.control_scaffold_id])
    _validate_budget_for_new_run()

    llm_api_key = _extract_llm_api_key(request)
    run_id = _gen_run_id("cmp")
    created_at = time.time()
    try:
        opts = RunOptions(**(req.options or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    queue: asyncio.Queue = asyncio.Queue()

    # Three cases
    cases = [
        {"case_id": "cheap_winning", "model_id": req.cheap_model_id, "scaffold_id": req.winning_scaffold_id},
        {"case_id": "expensive_bare", "model_id": req.expensive_model_id, "scaffold_id": req.control_scaffold_id},
        {"case_id": "expensive_winning", "model_id": req.expensive_model_id, "scaffold_id": req.winning_scaffold_id},
    ]

    async def _run_comparison():
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
            provider = get_provider(mid, api_key_override=llm_api_key)
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
        winner_id = None
        best_score = -1.0
        for cid, data in all_results.items():
            score = data.get("evaluation", {}).get("total_score", 0.0)
            if score > best_score:
                best_score = score
                winner_id = cid

        completed_at = time.time()
        persist_run(
            run_id=run_id,
            kind=RunKind.COMPARISON.value,
            task_id=req.task_id,
            model_id=req.expensive_model_id,
            scaffold_ids=[req.winning_scaffold_id, req.control_scaffold_id],
            options=opts.__dict__,
            created_at=created_at,
            completed_at=completed_at,
            winner_id=winner_id,
            status="completed",
            results=all_results,
        )
        if run_id in _runs:
            _runs[run_id]._done = True
            _runs[run_id].completed_at = completed_at
            _runs[run_id].results = all_results

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


class ModelComparisonRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    model_a_id: str = Field(min_length=1, max_length=128)
    model_b_id: str = Field(min_length=1, max_length=128)
    scaffold_id: str = Field(min_length=1, max_length=128)
    options: dict | None = None


@app.post("/api/model-comparisons")
@limiter.limit("10/minute")
async def create_model_comparison(
    request: Request,
    req: ModelComparisonRequest,
    _auth: None = Depends(verify_token),
):
    from core.run_engine import _gen_run_id, _run_single_scaffold, RunOptions, RunState
    from core.provider import get_provider
    from core import events as ev

    _validate_task_id(req.task_id)
    _validate_model_id(req.model_a_id)
    _validate_model_id(req.model_b_id)
    _validate_scaffold_ids([req.scaffold_id])
    _validate_budget_for_new_run()

    llm_api_key = _extract_llm_api_key(request)
    run_id = _gen_run_id("mcmp")
    created_at = time.time()
    try:
        opts = RunOptions(**(req.options or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    queue: asyncio.Queue = asyncio.Queue()
    cases = [
        {"case_id": "model_a", "model_id": req.model_a_id, "scaffold_id": req.scaffold_id},
        {"case_id": "model_b", "model_id": req.model_b_id, "scaffold_id": req.scaffold_id},
    ]

    async def _run_model_comparison():
        await queue.put(("comparison_started", ev.comparison_started(run_id, cases)))

        all_results = {}
        for case in cases:
            cid = case["case_id"]
            mid = case["model_id"]
            sid = case["scaffold_id"]

            case_run = RunState(
                run_id=run_id,
                kind=RunKind.COMPARISON,
                task_id=req.task_id,
                model_id=mid,
                scaffold_ids=[sid],
                options=opts,
                queue=asyncio.Queue(),
            )
            await queue.put(("case_started", ev.case_started(run_id, cid, mid, sid)))
            provider = get_provider(mid, api_key_override=llm_api_key)
            await _run_single_scaffold(case_run, sid, provider)

            result = case_run.results.get(sid, {})
            metrics = result.get("metrics", {})
            evaluation = result.get("evaluation", {})
            output = result.get("output", "")
            await queue.put(("case_completed", ev.case_completed(run_id, cid, output, metrics)))
            if evaluation:
                await queue.put(
                    (
                        "case_evaluation_completed",
                        ev.case_evaluation_completed(
                            run_id,
                            cid,
                            evaluation.get("total_score", 0),
                            evaluation.get("breakdown", {}),
                        ),
                    )
                )
            all_results[cid] = {
                "metrics": metrics,
                "evaluation": evaluation,
                "model_id": mid,
                "scaffold_id": sid,
            }

        await queue.put(("comparison_complete", ev.comparison_complete(run_id, all_results)))
        completed_at = time.time()
        winner_id = max(
            all_results,
            key=lambda cid: all_results[cid].get("evaluation", {}).get("total_score", 0),
        )
        persist_run(
            run_id=run_id,
            kind="model_comparison",
            task_id=req.task_id,
            model_id=req.model_a_id,
            scaffold_ids=[req.scaffold_id],
            options=opts.__dict__,
            created_at=created_at,
            completed_at=completed_at,
            winner_id=winner_id,
            status="completed",
            results=all_results,
        )
        if run_id in _runs:
            _runs[run_id]._done = True
            _runs[run_id].completed_at = completed_at
            _runs[run_id].results = all_results

    asyncio.create_task(_run_model_comparison())

    run = RunState(
        run_id=run_id,
        kind=RunKind.COMPARISON,
        task_id=req.task_id,
        model_id=req.model_a_id,
        scaffold_ids=[req.scaffold_id],
        options=opts,
        queue=queue,
    )
    _runs[run_id] = run
    return {"run_id": run_id, "stream_url": f"/api/runs/{run_id}/events"}


# --- Autopsy ---
class AutopsyRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    scaffold_id: str = Field(min_length=1, max_length=128)
    output: str = Field(min_length=1, max_length=200_000)
    evaluation: dict
    metrics: dict | None = None


@app.post("/api/autopsy")
@limiter.limit("10/minute")
async def autopsy(
    request: Request,
    req: AutopsyRequest,
    _auth: None = Depends(verify_token),
):
    from autopsy.analyzer import analyze_failures

    _validate_task_id(req.task_id)
    _validate_scaffold_ids([req.scaffold_id])

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
    task_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(default="claude-sonnet-4-6", min_length=1, max_length=128)
    scaffold_id: str = Field(min_length=1, max_length=128)
    base_config: dict = Field(default_factory=dict)
    patch: dict = Field(default_factory=dict)


@app.post("/api/patch-reruns")
@limiter.limit("10/minute")
async def patch_rerun(
    request: Request,
    req: PatchRerunRequest,
    _auth: None = Depends(verify_token),
):
    _validate_task_id(req.task_id)
    _validate_model_id(req.model_id)
    _validate_scaffold_ids([req.scaffold_id])
    _validate_budget_for_new_run()

    llm_api_key = _extract_llm_api_key(request)
    merged_config = {**req.base_config, **req.patch}
    run = create_run(
        kind=RunKind.PATCH_RERUN,
        task_id=req.task_id,
        model_id=req.model_id,
        scaffold_ids=[req.scaffold_id],
        options=None,
        llm_api_key=llm_api_key,
    )
    asyncio.create_task(start_patch_rerun(run, config_override=merged_config))
    return {
        "run_id": run.run_id,
        "stream_url": f"/api/runs/{run.run_id}/events",
    }


# --- Report ---
class ReportRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    results: dict
    comparison: dict | None = None
    autopsy: dict | None = None
    patch_rerun: dict | None = None


@app.post("/api/reports")
@limiter.limit("10/minute")
async def generate_report(
    request: Request,
    req: ReportRequest,
    _auth: None = Depends(verify_token),
):
    from report.markdown import generate_markdown

    _validate_task_id(req.task_id)
    _validate_model_id(req.model_id)

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


@app.get("/api/runs/{run_id}/export-bundle")
@limiter.limit("20/minute")
async def export_run_bundle(
    request: Request,
    run_id: str,
    _auth: None = Depends(verify_token),
):
    del request
    payload = _resolve_run_payload(run_id)
    status = payload.get("status")
    if status not in {"completed", "failed"}:
        raise HTTPException(status_code=409, detail="Run is still in progress; complete it before exporting.")

    results = payload.get("results", {})
    if not isinstance(results, dict) or not results:
        raise HTTPException(status_code=400, detail="Run does not include exportable results.")

    from report.markdown import generate_markdown

    markdown = generate_markdown(
        task_id=str(payload.get("task_id", "")),
        model_id=str(payload.get("model_id", "")),
        results=results,
        comparison=None,
        autopsy=None,
        patch_rerun=None,
    )

    run_metadata = {
        "run_id": payload.get("run_id"),
        "kind": payload.get("kind"),
        "status": payload.get("status"),
        "task_id": payload.get("task_id"),
        "model_id": payload.get("model_id"),
        "scaffold_ids": payload.get("scaffold_ids"),
        "options": payload.get("options"),
        "created_at": payload.get("created_at"),
        "completed_at": payload.get("completed_at"),
        "winner_id": payload.get("winner_id"),
    }
    diagnostics = payload.get("diagnostics", {})

    bundle_readme = (
        "Scaffold Arena Export Bundle\n"
        "===========================\n\n"
        "This bundle contains the canonical run payload, diagnostics timeline, and audit markdown.\n"
        "Synthetic-source tasks remain demo data and are clearly labeled in the report.\n"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", bundle_readme)
        zf.writestr("run.json", json.dumps({"metadata": run_metadata, "results": results}, indent=2))
        zf.writestr("diagnostics.json", json.dumps(diagnostics, indent=2))
        zf.writestr("report.md", markdown)

    buffer.seek(0)
    filename = f"scaffold-arena-{run_id}-bundle.zip"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


# --- Static frontend serving (production only) ---
_STATIC_DIR = Path(__file__).resolve().parent / "static"

if _STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="static-assets")

    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str):
        """Serve index.html for all non-API routes (SPA client-side routing)."""
        file_path = _STATIC_DIR / full_path
        if file_path.is_file() and ".." not in full_path:
            return FileResponse(file_path)
        return FileResponse(_STATIC_DIR / "index.html")
