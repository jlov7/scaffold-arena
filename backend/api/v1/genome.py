"""Read-mostly Harness Genome v1 endpoints; these routes never start providers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from services_v1 import GenomeError, GenomeService

router = APIRouter(prefix="/api/v1", tags=["genome-v1"])


def _service(request: Request) -> GenomeService:
    service = getattr(request.app.state, "genome_service", None)
    if not isinstance(service, GenomeService):
        raise GenomeError("genome_unavailable", "Genome services are not configured for this deployment.", status_code=503)
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get("project_id")


async def _body(request: Request) -> Mapping[str, Any]:
    try:
        value = await request.json()
    except Exception as exc:
        raise GenomeError("invalid_json", "A JSON object is required.") from exc
    if not isinstance(value, dict):
        raise GenomeError("invalid_json", "A JSON object is required.")
    return value


def _error(exc: GenomeError) -> JSONResponse:
    return public_service_error(exc)


async def _acp_hold(request: Request, operation: str, *, bridge_id: str | None = None) -> dict[str, Any]:
    """Public ACP routes are status-only: configuration is never request data."""
    body = await request.body()
    code = "acp_operator_service_required" if not body else "acp_inline_admission_denied"
    result: dict[str, Any] = {
        "verdict": "HOLD",
        "code": code,
        "operation": operation,
        "bridge_id": bridge_id,
        "prerequisite": "A deployment-owned resolver and digest-bound sandbox-launcher attestation are required; this route never admits caller-supplied registry, identity, argv, prompt, workspace, or policy data.",
        "provider_execution_started": False,
    }
    status = getattr(request.app.state, "acp_operator_status", None)
    if callable(status):
        configured = status(operation=operation, bridge_id=bridge_id)
        if isinstance(configured, Mapping) and configured.get("verdict") == "HOLD":
            result.update({key: value for key, value in configured.items() if key not in {"verdict", "provider_execution_started"}})
    return result


@router.post("/genomes/validate")
async def validate_genome(request: Request):
    try:
        return _service(request).validate(await _body(request))
    except GenomeError as exc:
        return _error(exc)


@router.post("/genomes")
async def register_genome(request: Request):
    try:
        return _service(request).register(await _body(request), project_id=_project_id(request))
    except GenomeError as exc:
        return _error(exc)


@router.get("/genomes")
async def list_genomes(request: Request):
    try:
        return _service(request).list(project_id=_project_id(request))
    except GenomeError as exc:
        return _error(exc)


@router.get("/genomes/{genome_id}")
async def get_genome(genome_id: str, request: Request):
    try:
        return _service(request).get(genome_id, project_id=_project_id(request)).model_dump(mode="json")
    except GenomeError as exc:
        return _error(exc)


@router.get("/genomes/{genome_id}/graph")
async def genome_graph(genome_id: str, request: Request):
    try:
        return _service(request).graph(genome_id, project_id=_project_id(request))
    except GenomeError as exc:
        return _error(exc)


@router.post("/genomes/diff")
async def genome_diff(request: Request):
    try:
        body = await _body(request)
        before, after = body.get("before"), body.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise GenomeError("genome_diff_invalid", "Genome diff requires strict before and after descriptors.")
        return _service(request).diff(before, after)
    except GenomeError as exc:
        return _error(exc)


@router.get("/standards/catalog")
async def standards_catalog(protocol: str | None = None):
    return GenomeService.catalog(protocol)


@router.post("/genomes/{genome_id}/certify")
async def certify_genome(genome_id: str, request: Request):
    try:
        return _service(request).certify(genome_id, project_id=_project_id(request))
    except GenomeError as exc:
        return _error(exc)


@router.get("/genomes/{genome_id}/certify")
async def get_genome_certification(genome_id: str, request: Request):
    try:
        return _service(request).certification(genome_id, project_id=_project_id(request))
    except GenomeError as exc:
        return _error(exc)


@router.get("/acp/registry")
async def acp_registry(request: Request):
    return await _acp_hold(request, "registry")


@router.post("/acp/certify")
async def acp_certify(request: Request):
    return await _acp_hold(request, "certify")


@router.post("/acp/validate")
async def acp_validate(request: Request):
    return await _acp_hold(request, "validate")


@router.post("/acp/runs")
async def acp_run(request: Request):
    return await _acp_hold(request, "run")


@router.post("/acp/runs/{bridge_id}/cancel")
async def acp_cancel(bridge_id: str, request: Request):
    return await _acp_hold(request, "cancel", bridge_id=bridge_id)


@router.get("/acp/runs/{bridge_id}/events")
async def acp_events(bridge_id: str, request: Request):
    return await _acp_hold(request, "events", bridge_id=bridge_id)
