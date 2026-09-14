"""Public, non-executing protocol registry endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from services_v1 import ProtocolRegistryService, RegistryError

router = APIRouter(prefix="/api/v1", tags=["protocol-v1"])


def _service(request: Request) -> ProtocolRegistryService:
    service = getattr(request.app.state, "protocol_registry_service", None)
    if not isinstance(service, ProtocolRegistryService):
        raise RegistryError("registry_unavailable", "The protocol registry is not configured for this local deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get("project_id")


def _error(exc: RegistryError) -> JSONResponse:
    return public_service_error(exc)


async def _json_body(request: Request) -> Mapping[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise RegistryError("invalid_json", "A JSON request body is required.") from exc
    if not isinstance(body, dict):
        raise RegistryError("invalid_json", "A JSON object is required.")
    return body


@router.post("/study-packs/validate")
async def validate_study_pack(request: Request):
    try:
        result = _service(request).validate_pack(await request.body(), request.headers.get("content-type", ""))
        return JSONResponse(status_code=200 if result["valid"] else 422, content=result)
    except RegistryError as exc:
        return _error(exc)


@router.post("/study-packs/import")
async def import_study_pack(request: Request):
    try:
        return _service(request).import_pack(
            await request.body(), request.headers.get("content-type", ""), project_id=_project_id(request)
        )
    except RegistryError as exc:
        return _error(exc)


@router.get("/study-packs")
async def list_study_packs(request: Request):
    try:
        return {"study_packs": _service(request).list_packs(project_id=_project_id(request)), "authority_ceiling": "personal/local authority only"}
    except RegistryError as exc:
        return _error(exc)


@router.get("/study-packs/{pack_key}/versions/{version}")
async def get_study_pack(pack_key: str, version: str, request: Request):
    try:
        return _service(request).study_pack(pack_key, version, project_id=_project_id(request))
    except RegistryError as exc:
        return _error(exc)


@router.post("/experiments")
async def create_experiment(request: Request):
    try:
        return _service(request).create_experiment(await _json_body(request), project_id=_project_id(request))
    except RegistryError as exc:
        return _error(exc)


@router.get("/experiments")
async def list_experiments(
    request: Request, study_pack_id: str | None = None, study_pack_version: str | None = None,
):
    try:
        return {"experiments": _service(request).list_experiments(
            project_id=_project_id(request), study_pack_id=study_pack_id, study_pack_version=study_pack_version,
        )}
    except RegistryError as exc:
        return _error(exc)


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: str, request: Request):
    try:
        return _service(request).experiment(experiment_id, project_id=_project_id(request))
    except RegistryError as exc:
        return _error(exc)


@router.post("/experiments/{experiment_id}/freeze")
async def freeze_experiment_endpoint(experiment_id: str, request: Request):
    try:
        return _service(request).freeze(experiment_id, project_id=_project_id(request))
    except RegistryError as exc:
        return _error(exc)


@router.post("/experiments/{experiment_id}/preflight")
async def preflight_experiment(experiment_id: str, request: Request):
    try:
        return _service(request).preflight(experiment_id, project_id=_project_id(request)
        )
    except RegistryError as exc:
        return _error(exc)
