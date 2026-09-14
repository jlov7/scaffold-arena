"""Project-scoped durable Decision Brief endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from analysis_v1 import DecisionAdmissionRequest
from api.public_errors import public_service_error
from services_v1 import DecisionError, DecisionService

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-decision"])


def _service(request: Request) -> DecisionService:
    service = getattr(request.app.state, "decision_service", None)
    if not isinstance(service, DecisionService):
        raise DecisionError("decision_unavailable", "Decision services are not configured for this deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get("project_id")


def _error(exc: DecisionError) -> JSONResponse:
    return public_service_error(exc)


@router.post("/decision-briefs")
async def create_decision_brief(payload: DecisionAdmissionRequest, request: Request):
    try:
        return _service(request).create(
            payload.model_dump(mode="json", exclude_none=True),
            project_id=_project_id(request),
        )
    except DecisionError as exc:
        return _error(exc)


@router.get("/decision-briefs")
async def list_decision_briefs(
    request: Request,
    execution_id: str | None = None,
    report_digest: str | None = None,
    verdict: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    try:
        return _service(request).list(
            project_id=_project_id(request), execution_id=execution_id,
            report_digest=report_digest, verdict=verdict, limit=limit, offset=offset,
        )
    except DecisionError as exc:
        return _error(exc)


@router.get("/decision-briefs/{decision_id}")
async def get_decision_brief(decision_id: str, request: Request):
    try:
        return _service(request).get(decision_id, project_id=_project_id(request))
    except DecisionError as exc:
        return _error(exc)
