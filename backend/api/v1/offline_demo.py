"""Bounded personal-profile API for the bundled offline fixture journey."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from services_v1.offline_demo import OfflineDemoError, OfflineDemoService

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-offline-demo"])


def _service(request: Request) -> OfflineDemoService:
    service = getattr(request.app.state, "offline_demo_service", None)
    if not isinstance(service, OfflineDemoService):
        detail = getattr(request.app.state, "offline_demo_unavailable_reason", None)
        raise OfflineDemoError("offline_demo_unavailable", detail or "The bundled offline demonstration is unavailable.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get("project_id")


def _is_loopback_name(value: str | None, *, allow_localhost: bool) -> bool:
    if not value:
        return False
    if allow_localhost and value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _require_local_request(request: Request) -> None:
    """Defence in depth for the launcher-owned local-only capability.

    Forwarded headers are deliberately ignored. A reverse proxy is not a
    supported way to expose this fixture; the trusted launcher binds directly
    to a literal loopback address.
    """
    peer = request.client.host if request.client is not None else None
    if not _is_loopback_name(peer, allow_localhost=False):
        raise OfflineDemoError("offline_demo_local_runtime_required", "The bundled offline demonstration accepts only direct loopback requests.", status_code=403)
    host = request.headers.get("host")
    if host:
        parsed = urlsplit(f"//{host}")
        if parsed.username or parsed.password or not _is_loopback_name(parsed.hostname, allow_localhost=True):
            raise OfflineDemoError("offline_demo_local_runtime_required", "The bundled offline demonstration requires a loopback host.", status_code=403)
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not _is_loopback_name(parsed.hostname, allow_localhost=True):
            raise OfflineDemoError("offline_demo_local_runtime_required", "The bundled offline demonstration requires a loopback browser origin.", status_code=403)


@router.post("/offline-demo")
async def start_offline_demo(request: Request):
    try:
        service = _service(request)
        _require_local_request(request)
        return service.start(project_id=_project_id(request))
    except OfflineDemoError as exc:
        return public_service_error(exc)


@router.post("/offline-demo/experiments/{experiment_id}/execute")
async def execute_offline_demo(experiment_id: str, request: Request):
    try:
        service = _service(request)
        _require_local_request(request)
        return await service.execute(
            experiment_id,
            project_id=_project_id(request),
            request_key=request.headers.get("idempotency-key"),
        )
    except OfflineDemoError as exc:
        return public_service_error(exc)
