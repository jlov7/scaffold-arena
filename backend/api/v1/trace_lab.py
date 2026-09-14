"""Trace Lab v1 admission endpoint."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request

from api.public_errors import public_service_error
from services_v1.trace_lab import TraceLabError, TraceLabService

router = APIRouter(prefix="/api/v1", tags=["trace-lab-v1"])


def _service(request: Request) -> TraceLabService:
    service = getattr(request.app.state, "trace_lab_service", None)
    if not isinstance(service, TraceLabService):
        raise TraceLabError("trace_lab_unavailable", "Trace Lab is not configured for this deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get("project_id")


async def _body(request: Request) -> Mapping[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise TraceLabError("invalid_json", "A JSON object trace-analysis request is required.") from exc
    if not isinstance(body, dict):
        raise TraceLabError("invalid_json", "A JSON object trace-analysis request is required.")
    return body


@router.post("/trace-analyses")
async def create_trace_analysis(request: Request):
    try:
        return _service(request).analyze(await _body(request), project_id=_project_id(request))
    except TraceLabError as exc:
        return public_service_error(exc)
