"""Read and snapshot exact persisted attempt-event ledgers."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from services_v1.observatory import ObservatoryError, ObservatoryService

router = APIRouter(prefix="/api/v1", tags=["observatory-v1"])


def _service(request: Request) -> ObservatoryService:
    service = getattr(request.app.state, "observatory_service", None)
    if not isinstance(service, ObservatoryService):
        raise ObservatoryError("observatory_unavailable", "Observatory services are not configured for this deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    value = getattr(request.state, "arena_project_id", None)
    return value if isinstance(value, str) else None


def _error(exc: ObservatoryError) -> JSONResponse:
    return public_service_error(exc)


@router.get("/observatory/attempts/{attempt_id}")
async def observe_attempt(attempt_id: str, request: Request):
    try:
        return _service(request).ledger(attempt_id, project_id=_project_id(request))
    except ObservatoryError as exc:
        return _error(exc)


@router.post("/observatory/attempts/{attempt_id}/reports")
async def capture_observatory_report(attempt_id: str, request: Request):
    try:
        return _service(request).capture(attempt_id, project_id=_project_id(request))
    except ObservatoryError as exc:
        return _error(exc)


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise ObservatoryError("invalid_json", "A JSON object is required.") from exc
    if not isinstance(body, dict):
        raise ObservatoryError("invalid_json", "A JSON object is required.")
    return body


@router.post("/observatory-analyses")
@router.post("/observatory/reports")
async def create_observatory_analysis(request: Request):
    try:
        return _service(request).create_report(await _body(request), project_id=_project_id(request))
    except ObservatoryError as exc:
        return _error(exc)


@router.get("/observatory-analyses/{report_digest}")
async def get_observatory_analysis(report_digest: str, request: Request):
    try:
        return _service(request).analysis(report_digest, project_id=_project_id(request))
    except ObservatoryError as exc:
        return _error(exc)


@router.get("/observatory/reports/{report_ref}")
async def get_observatory_report(report_ref: str, request: Request):
    """Keep the older ledger route while allowing a digest report alias.

    Legacy ledger report ids start with ``x``; analysis references are a
    SHA-256 digest. Dispatching by the strict digest shape avoids two FastAPI
    routes with the same method and path template.
    """
    bare_digest = report_ref.removeprefix("sha256:")
    try:
        if len(bare_digest) == 64 and all(character in "0123456789abcdef" for character in bare_digest):
            return _service(request).analysis(report_ref, project_id=_project_id(request))
        return _service(request).report(report_ref, project_id=_project_id(request))
    except ObservatoryError as exc:
        return _error(exc)
