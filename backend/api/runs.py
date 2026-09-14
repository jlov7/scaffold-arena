from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.deps import (
    extract_llm_api_key,
    idempotency_fingerprint,
    limiter,
    lookup_idempotent_response,
    store_idempotent_response,
    validate_budget_for_new_run,
    validate_model_id,
    validate_scaffold_ids,
    validate_task_id,
)
from core.auth import verify_token
from core.provider_errors import sanitize_provider_error
from core.run_engine import (
    RunEvictedError,
    RunKind,
    _runs,
    build_run_diagnostics,
    cancel_run,
    create_run,
    get_event_stream,
    get_run,
    start_arena_run,
    start_patch_rerun,
)
from core.stats import compute_stats
from core.storage import get_run_record, list_runs

router = APIRouter(tags=["runs"])

RunStarter = Callable[..., Awaitable[None]]
_arena_run_starter: RunStarter = start_arena_run
_patch_rerun_starter: RunStarter = start_patch_rerun


def configure_run_starters(
    *,
    arena_run_starter: RunStarter,
    patch_rerun_starter: RunStarter,
) -> None:
    global _arena_run_starter, _patch_rerun_starter
    _arena_run_starter = arena_run_starter
    _patch_rerun_starter = patch_rerun_starter


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


def _preflight_check(
    check_id: str, status: str, message: str, action: str | None = None
) -> dict:
    payload = {"id": check_id, "status": status, "message": message}
    if action:
        payload["action"] = action
    return payload


def live_run_payload(run: Any) -> dict:
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


@router.post("/api/preflight")
@limiter.limit("20/minute")
async def run_preflight(
    request: Request,
    req: RunPreflightRequest,
    _auth: None = Depends(verify_token),
):
    checks: list[dict] = []
    for check_id, validator, value, success, action in (
        ("task", validate_task_id, req.task_id, "Task is valid.", "Select a task listed in the Task selector."),
        ("model", validate_model_id, req.model_id, "Model is valid.", "Choose a model from the current model registry."),
        ("scaffolds", validate_scaffold_ids, req.scaffold_ids, "Scaffold selection is valid.", "Adjust scaffold selection before running."),
    ):
        try:
            validator(value)
            checks.append(_preflight_check(check_id, "pass", success))
        except HTTPException as exc:
            checks.append(_preflight_check(check_id, "fail", str(exc.detail), action))

    try:
        from core.run_engine import RunOptions

        RunOptions(**(req.options or {}))
        checks.append(_preflight_check("options", "pass", "Run options are valid."))
    except ValueError:
        checks.append(_preflight_check("options", "fail", "Run options are invalid.", "Fix run options in Settings before starting."))

    try:
        validate_budget_for_new_run()
        checks.append(_preflight_check("budget", "pass", "Budget allows a new run."))
    except HTTPException as exc:
        checks.append(_preflight_check("budget", "fail", str(exc.detail), "Increase budget or wait for next daily rollover."))

    try:
        from core.provider import get_provider

        get_provider(req.model_id, api_key_override=extract_llm_api_key(request))
        checks.append(_preflight_check("provider", "pass", "Provider credentials are ready."))
    # Provider SDKs expose provider-specific exception classes; preflight must
    # surface every initialization failure as a non-runnable state.
    except Exception as exc:  # noqa: BLE001
        checks.append(
            _preflight_check(
                "provider",
                "fail",
                sanitize_provider_error(exc),
                "Set a valid provider key in Settings (BYOK) or backend environment.",
            )
        )

    ok = all(check["status"] != "fail" for check in checks)
    return {"ok": ok, "can_run": ok, "checked_at": time.time(), "checks": checks}


@router.get("/api/runs")
async def get_runs(limit: int = 50):
    stored = list_runs(limit=max(1, min(limit, 500)))
    live = [live_run_payload(run) for run in _runs.values() if not run._done]
    combined = live + stored
    combined.sort(
        key=lambda run: float(run.get("completed_at") or run.get("created_at") or 0),
        reverse=True,
    )
    return {"runs": combined}


@router.get("/api/stats")
async def get_stats(limit: int = 1000):
    return compute_stats(limit=limit)


@router.post("/api/runs")
@limiter.limit("5/minute")
async def create_arena_run(
    request: Request,
    req: CreateRunRequest,
    _auth: None = Depends(verify_token),
):
    llm_api_key = extract_llm_api_key(request)
    idempotency_key = (request.headers.get("x-idempotency-key") or "").strip()
    if idempotency_key:
        fingerprint = idempotency_fingerprint(req.model_dump(mode="json"), llm_api_key)
        cached_response = lookup_idempotent_response(idempotency_key, fingerprint)
        if cached_response is not None:
            return cached_response

    validate_model_id(req.model_id)
    validate_scaffold_ids(req.scaffold_ids)
    validate_budget_for_new_run()
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
        validate_task_id(req.task_id)

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
        raise HTTPException(status_code=400, detail="Run options are invalid.") from exc

    asyncio.create_task(_arena_run_starter(run))
    response = {
        "run_id": run.run_id,
        "stream_url": f"/api/runs/{run.run_id}/events",
        "cancel_url": f"/api/runs/{run.run_id}/cancel",
        "idempotent_replay": False,
    }
    if idempotency_key:
        store_idempotent_response(idempotency_key, fingerprint, response)
    return response


@router.get("/api/runs/{run_id}")
async def get_run_details(run_id: str):
    try:
        return live_run_payload(get_run(run_id))
    except (RunEvictedError, ValueError):
        record = get_run_record(run_id)
        if record:
            return record
        raise HTTPException(404, "Run not found")


@router.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str):
    try:
        get_run(run_id)
    except RunEvictedError:
        raise HTTPException(410, "Run has been evicted")
    except ValueError:
        raise HTTPException(404, "Run not found")
    return EventSourceResponse(_sse_generator(run_id), media_type="text/event-stream")


def build_stored_run_diagnostics(record: dict) -> dict:
    timeline: list[dict] = []
    created_ts_ms = int(float(record.get("created_at") or time.time()) * 1000)
    timeline.append({"seq": 1, "event": "run_started", "ts_ms": created_ts_ms, "scaffold_id": None, "summary": "Run started"})
    event_counts: dict[str, int] = {"run_started": 1, "run_complete": 1}
    scaffold_status: dict[str, str] = {}
    errors: dict[str, str] = {}
    for scaffold_id, result in (record.get("results") or {}).items():
        has_error = isinstance(result, dict) and "error" in result
        event = "scaffold_failed" if has_error else "scaffold_completed"
        status = "failed" if has_error else "completed"
        event_counts[event] = event_counts.get(event, 0) + 1
        scaffold_status[scaffold_id] = status
        if has_error:
            errors[scaffold_id] = "Scaffold execution failed."
        timeline.append({"seq": len(timeline) + 1, "event": event, "ts_ms": created_ts_ms + (len(timeline) + 1) * 5, "scaffold_id": scaffold_id, "summary": f"{scaffold_id} {status}"})
        if not has_error and isinstance(result, dict) and result.get("evaluation"):
            event_counts["evaluation_completed"] = event_counts.get("evaluation_completed", 0) + 1
            timeline.append({"seq": len(timeline) + 1, "event": "evaluation_completed", "ts_ms": created_ts_ms + (len(timeline) + 1) * 5, "scaffold_id": scaffold_id, "summary": f"{scaffold_id} scored"})
    timeline.append({"seq": len(timeline) + 1, "event": "run_complete", "ts_ms": int(float(record.get("completed_at") or record.get("created_at") or time.time()) * 1000), "scaffold_id": None, "summary": "Run completed"})
    duration_ms = None
    if record.get("completed_at") and record.get("created_at"):
        duration_ms = int((float(record["completed_at"]) - float(record["created_at"])) * 1000)
    return {
        "run_id": record.get("run_id"), "kind": record.get("kind"), "status": record.get("status"),
        "created_at": record.get("created_at"), "completed_at": record.get("completed_at"), "duration_ms": duration_ms,
        "task_id": record.get("task_id"), "model_id": record.get("model_id"), "scaffold_ids": record.get("scaffold_ids", []),
        "options": record.get("options", {}), "event_count": len(timeline), "event_type_counts": event_counts,
        "scaffold_status": scaffold_status, "errors": errors, "timeline": timeline,
    }


def resolve_run_payload(run_id: str) -> dict:
    try:
        run = get_run(run_id)
        payload = live_run_payload(run)
        payload["diagnostics"] = build_run_diagnostics(run)
        return payload
    except (RunEvictedError, ValueError):
        record = get_run_record(run_id)
        if not record:
            raise HTTPException(404, "Run not found")
        payload = dict(record)
        payload["diagnostics"] = build_stored_run_diagnostics(record)
        return payload


@router.get("/api/runs/{run_id}/diagnostics")
async def get_run_diagnostics(run_id: str):
    return resolve_run_payload(run_id)["diagnostics"]


async def _sse_generator(run_id: str):
    async for frame in get_event_stream(run_id):
        yield frame


@router.post("/api/runs/{run_id}/cancel")
@limiter.limit("10/minute")
async def cancel(request: Request, run_id: str, _auth: None = Depends(verify_token)):
    try:
        cancel_run(run_id)
    except RunEvictedError:
        raise HTTPException(410, "Run has been evicted")
    except ValueError:
        raise HTTPException(404, "Run not found")
    return {"status": "cancelled"}


class PatchRerunRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(default="claude-sonnet-4-6", min_length=1, max_length=128)
    scaffold_id: str = Field(min_length=1, max_length=128)
    base_config: dict = Field(default_factory=dict)
    patch: dict = Field(default_factory=dict)


@router.post("/api/patch-reruns")
@limiter.limit("10/minute")
async def patch_rerun(
    request: Request,
    req: PatchRerunRequest,
    _auth: None = Depends(verify_token),
):
    validate_task_id(req.task_id)
    validate_model_id(req.model_id)
    validate_scaffold_ids([req.scaffold_id])
    validate_budget_for_new_run()
    run = create_run(
        kind=RunKind.PATCH_RERUN,
        task_id=req.task_id,
        model_id=req.model_id,
        scaffold_ids=[req.scaffold_id],
        options=None,
        llm_api_key=extract_llm_api_key(request),
    )
    asyncio.create_task(
        _patch_rerun_starter(run, config_override={**req.base_config, **req.patch})
    )
    return {"run_id": run.run_id, "stream_url": f"/api/runs/{run.run_id}/events"}


@router.get("/api/runs/{run_id}/export-bundle")
@limiter.limit("20/minute")
async def export_run_bundle(
    request: Request,
    run_id: str,
    _auth: None = Depends(verify_token),
):
    del request
    payload = resolve_run_payload(run_id)
    if payload.get("status") not in {"completed", "failed"}:
        raise HTTPException(status_code=409, detail="Run is still in progress; complete it before exporting.")
    results = payload.get("results", {})
    if not isinstance(results, dict) or not results:
        raise HTTPException(status_code=400, detail="Run does not include exportable results.")
    from report.markdown import generate_markdown

    markdown = generate_markdown(
        task_id=str(payload.get("task_id", "")), model_id=str(payload.get("model_id", "")), results=results,
        comparison=None, autopsy=None, patch_rerun=None,
    )
    metadata = {key: payload.get(key) for key in ("run_id", "kind", "status", "task_id", "model_id", "scaffold_ids", "options", "created_at", "completed_at", "winner_id")}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", "Scaffold Arena Export Bundle\n===========================\n\nThis bundle contains the canonical run payload, diagnostics timeline, and audit markdown.\nSynthetic-source tasks remain demo data and are clearly labeled in the report.\n")
        zf.writestr("run.json", json.dumps({"metadata": metadata, "results": results}, indent=2))
        zf.writestr("diagnostics.json", json.dumps(payload.get("diagnostics", {}), indent=2))
        zf.writestr("report.md", markdown)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="scaffold-arena-{run_id}-bundle.zip"'})
