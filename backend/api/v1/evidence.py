"""Read-only evidence inspection and integrity verification endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from evidence_v1 import (
    DerivedEvidenceRequest,
    EvidenceAdmissionRequest,
    ReproductionRequest,
)
from services_v1 import EvidenceError, EvidenceService

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-evidence"])


def _service(request: Request) -> EvidenceService:
    service = getattr(request.app.state, "evidence_service", None)
    if not isinstance(service, EvidenceService):
        raise EvidenceError("evidence_unavailable", "Evidence services are not configured for this deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get("project_id")


def _error(exc: EvidenceError) -> JSONResponse:
    return public_service_error(exc)


@router.post("/evidence")
async def record_evidence(payload: EvidenceAdmissionRequest, request: Request):
    try:
        return _service(request).record_receipt(payload.model_dump(mode="json"), project_id=_project_id(request))
    except EvidenceError as exc:
        return _error(exc)


@router.get("/evidence")
async def list_evidence(
    request: Request,
    execution_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    try:
        return _service(request).list_receipts(
            project_id=_project_id(request), execution_id=execution_id, kind=kind,
            limit=limit, offset=offset,
        )
    except EvidenceError as exc:
        return _error(exc)


@router.post("/evidence/derive")
async def derive_execution_evidence(payload: DerivedEvidenceRequest, request: Request):
    try:
        return _service(request).derive_execution_receipt(payload.model_dump(mode="json"), project_id=_project_id(request))
    except EvidenceError as exc:
        return _error(exc)


@router.get("/evidence/{receipt_id}")
async def get_evidence(receipt_id: str, request: Request):
    try:
        return _service(request).get_receipt(receipt_id, project_id=_project_id(request))
    except EvidenceError as exc:
        return _error(exc)


@router.post("/evidence/{receipt_id}/verify")
async def verify_evidence(receipt_id: str, request: Request):
    try:
        return _service(request).verify_receipt(receipt_id, project_id=_project_id(request))
    except EvidenceError as exc:
        return _error(exc)


@router.post("/reproductions")
async def create_reproduction(payload: ReproductionRequest, request: Request):
    try:
        return _service(request).create_reproduction(payload.model_dump(mode="json"), project_id=_project_id(request))
    except EvidenceError as exc:
        return _error(exc)
