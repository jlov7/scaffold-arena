"""Durable execution-control endpoints; they never invoke a provider."""

from __future__ import annotations

import json
from asyncio import sleep
from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.public_errors import public_service_error
from services_v1.execution import (
    ExecutionError,
    ExecutionService,
    PersistedExecutionEvent,
)

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-execution"])


def _service(request: Request) -> ExecutionService:
    service = getattr(request.app.state, "execution_api_service", None)
    if not isinstance(service, ExecutionService):
        raise ExecutionError("execution_unavailable", "Execution control is not configured for this deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get("project_id")


def _error(exc: ExecutionError) -> JSONResponse:
    return public_service_error(exc)


async def _json_body(request: Request) -> Mapping[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise ExecutionError("invalid_json", "A JSON object body is required.") from exc
    if not isinstance(body, dict):
        raise ExecutionError("invalid_json", "A JSON object body is required.")
    return body


@router.post("/experiments/{experiment_id}/executions")
async def create_execution(experiment_id: str, request: Request):
    try:
        return _service(request).create_execution(
            experiment_id,
            await _json_body(request),
            project_id=_project_id(request),
            request_key=request.headers.get("idempotency-key"),
        )
    except ExecutionError as exc:
        return _error(exc)


@router.get("/executions")
async def list_executions(request: Request, experiment_id: str | None = None, limit: int = 50, offset: int = 0):
    try:
        return _service(request).list_executions(
            project_id=_project_id(request), experiment_id=experiment_id, limit=limit, offset=offset,
        )
    except ExecutionError as exc:
        return _error(exc)


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str, request: Request):
    try:
        return _service(request).execution(execution_id, project_id=_project_id(request))
    except ExecutionError as exc:
        return _error(exc)


@router.get("/executions/{execution_id}/events")
async def execution_events(execution_id: str, request: Request):
    cursor = request.query_params.get("cursor") or request.headers.get("last-event-id")
    try:
        events, terminal = _service(request).events(execution_id, project_id=_project_id(request), cursor=cursor)
    except ExecutionError as exc:
        return _error(exc)

    async def stream() -> AsyncIterator[str]:
        current = int(cursor or 0)
        pending = events
        terminal_status = terminal
        while True:
            for event in pending:
                current = event.cursor
                yield _sse_event(event)
            if terminal_status is not None:
                yield _sse("terminal", {"execution_id": execution_id, "status": terminal_status})
                return
            if await request.is_disconnected():
                return
            await sleep(0.1)
            try:
                pending, terminal_status = _service(request).events(
                    execution_id, project_id=_project_id(request), cursor=str(current),
                )
            except ExecutionError:
                return

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(execution_id: str, request: Request):
    try:
        return _service(request).cancel(execution_id, project_id=_project_id(request))
    except ExecutionError as exc:
        return _error(exc)


@router.post("/executions/{execution_id}/resume")
async def resume_execution(execution_id: str, request: Request):
    try:
        return _service(request).resume(execution_id, project_id=_project_id(request))
    except ExecutionError as exc:
        return _error(exc)


@router.get("/attempts/{attempt_id}")
async def get_attempt(attempt_id: str, request: Request):
    try:
        return _service(request).attempt(attempt_id, project_id=_project_id(request))
    except ExecutionError as exc:
        return _error(exc)


@router.get("/attempts/{attempt_id}/trace")
async def get_attempt_trace(attempt_id: str, request: Request):
    try:
        return _service(request).trace(attempt_id, project_id=_project_id(request))
    except ExecutionError as exc:
        return _error(exc)


def _sse_event(event: PersistedExecutionEvent) -> str:
    return _sse(
        event.event_type,
        {
            "event_id": event.event_id,
            "attempt_id": event.attempt_id,
            "attempt_sequence": event.attempt_sequence,
            "event_type": event.event_type,
            "payload": event.payload,
            "created_at": event.created_at,
        },
        event_id=str(event.cursor),
    )


def _sse(event_type: str, payload: Mapping[str, Any], *, event_id: str | None = None) -> str:
    identifier = f"id: {event_id}\n" if event_id is not None else ""
    return f"{identifier}event: {event_type}\ndata: {json.dumps(payload, default=str, separators=(',', ':'))}\n\n"
