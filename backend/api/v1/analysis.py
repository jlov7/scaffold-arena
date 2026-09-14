"""Project-scoped immutable Analysis v1 endpoint."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request

from api.public_errors import public_service_error
from services_v1 import AnalysisError, AnalysisService

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-analysis"])


def _service(request: Request) -> AnalysisService:
    service = getattr(request.app.state, "analysis_service", None)
    if not isinstance(service, AnalysisService):
        raise AnalysisError(
            "analysis_unavailable",
            "Analysis services are not configured for this deployment.",
            status_code=503,
        )
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get(
        "project_id"
    )


async def _body(request: Request) -> Mapping[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise AnalysisError(
            "invalid_json", "A JSON object analysis request is required."
        ) from exc
    if not isinstance(body, dict):
        raise AnalysisError(
            "invalid_json", "A JSON object analysis request is required."
        )
    return body


@router.post("/analysis")
async def analyze(request: Request):
    try:
        return _service(request).analyze(
            await _body(request), project_id=_project_id(request)
        )
    except AnalysisError as exc:
        return public_service_error(exc)


@router.get("/analysis-reports")
async def list_analysis_reports(
    request: Request,
    experiment_id: str | None = None,
    execution_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    try:
        return _service(request).list_reports(
            project_id=_project_id(request),
            experiment_id=experiment_id,
            execution_id=execution_id,
            limit=limit,
            offset=offset,
        )
    except AnalysisError as exc:
        return public_service_error(exc)


@router.get("/analysis-reports/{report_digest}")
async def get_analysis_report(report_digest: str, request: Request):
    try:
        return _service(request).report(report_digest, project_id=_project_id(request))
    except AnalysisError as exc:
        return public_service_error(exc)
