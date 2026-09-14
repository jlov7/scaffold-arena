"""Provider-free X-Ray source snapshot endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from services_v1.xray import XrayError, XrayService

router = APIRouter(prefix="/api/v1", tags=["xray-v1"])


def _service(request: Request) -> XrayService:
    service = getattr(request.app.state, "xray_service", None)
    if not isinstance(service, XrayService):
        raise XrayError("xray_unavailable", "X-Ray services are not configured for this deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    """Only trust the project resolved by the team-auth middleware.

    Personal mode intentionally returns None so the runtime's fixed personal
    project is used; callers cannot choose another local project by header.
    """
    value = getattr(request.state, "arena_project_id", None)
    return value if isinstance(value, str) else None


async def _body(request: Request) -> Mapping[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise XrayError("invalid_json", "A JSON object is required.") from exc
    if not isinstance(payload, dict):
        raise XrayError("invalid_json", "A JSON object is required.")
    return payload


def _error(exc: XrayError) -> JSONResponse:
    return public_service_error(exc)


@router.post("/xray/validate")
async def validate_xray_snapshot(request: Request):
    try:
        return _service(request).validate(await _body(request))
    except XrayError as exc:
        return _error(exc)


@router.post("/xray/snapshots")
async def ingest_xray_snapshot(request: Request):
    try:
        return _service(request).ingest(await _body(request), project_id=_project_id(request))
    except XrayError as exc:
        return _error(exc)


@router.post("/xray-analyses")
@router.post("/xray/reports")
async def create_xray_report(request: Request):
    try:
        return _service(request).create_report(await _body(request), project_id=_project_id(request))
    except XrayError as exc:
        return _error(exc)


@router.get("/xray-analyses/{report_digest}")
@router.get("/xray/reports/{report_digest}")
async def get_xray_report(report_digest: str, request: Request):
    try:
        return _service(request).report(report_digest, project_id=_project_id(request))
    except XrayError as exc:
        return _error(exc)


@router.get("/xray/snapshots")
async def list_xray_snapshots(request: Request):
    try:
        return _service(request).list(project_id=_project_id(request))
    except XrayError as exc:
        return _error(exc)


@router.get("/xray/snapshots/{snapshot_id}")
async def get_xray_snapshot(snapshot_id: str, request: Request):
    try:
        return _service(request).get(snapshot_id, project_id=_project_id(request))
    except XrayError as exc:
        return _error(exc)
