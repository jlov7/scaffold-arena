"""Project-scoped admission for immutable blind-review batches."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from review_v1 import AdjudicationSubmission, AnnotationBatch, AnnotationSubmission
from services_v1 import ReviewError, ReviewService

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-review"])


def _service(request: Request) -> ReviewService:
    service = getattr(request.app.state, "review_service", None)
    if not isinstance(service, ReviewService):
        raise ReviewError("review_unavailable", "Review services are not configured for this deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get("project_id")


def _error(exc: ReviewError) -> JSONResponse:
    return public_service_error(exc)


@router.post("/annotation-batches")
async def create_annotation_batch(payload: AnnotationBatch, request: Request):
    try:
        return _service(request).create_annotation_batch(payload.model_dump(mode="json"), project_id=_project_id(request))
    except ReviewError as exc:
        return _error(exc)


@router.get("/annotation-batches")
async def list_annotation_batches(
    request: Request,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    try:
        return _service(request).list_annotation_batches(
            project_id=_project_id(request), status=status, limit=limit, offset=offset,
        )
    except ReviewError as exc:
        return _error(exc)


@router.get("/annotation-batches/{batch_id}")
async def get_annotation_batch(batch_id: str, request: Request):
    try:
        return _service(request).batch_view(
            batch_id, request.query_params.get("annotator_pseudonym"), project_id=_project_id(request),
        )
    except ReviewError as exc:
        return _error(exc)


@router.get("/annotation-batches/{batch_id}/assignments/{assignment_id}")
async def get_assignment(batch_id: str, assignment_id: str, request: Request):
    try:
        return _service(request).assignment_view(
            batch_id, assignment_id, request.query_params.get("annotator_pseudonym"), project_id=_project_id(request),
        )
    except ReviewError as exc:
        return _error(exc)


@router.post("/annotation-batches/{batch_id}/annotations")
async def submit_annotation(batch_id: str, payload: AnnotationSubmission, request: Request):
    try:
        return _service(request).submit_annotation(batch_id, payload.model_dump(mode="json"), project_id=_project_id(request))
    except ReviewError as exc:
        return _error(exc)


@router.post("/annotation-batches/{batch_id}/adjudications")
async def submit_adjudication(batch_id: str, payload: AdjudicationSubmission, request: Request):
    try:
        return _service(request).submit_adjudication(batch_id, payload.model_dump(mode="json"), project_id=_project_id(request))
    except ReviewError as exc:
        return _error(exc)
