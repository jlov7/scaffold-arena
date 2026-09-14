"""Provider-free Arena Forge, planning, and process-safety API boundary."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from services_v1.forge import ExperimentPlannerService, ForgeError, ForgeService, ProcessSafetyService


router = APIRouter(prefix="/api/v1", tags=["arena-forge-v1"])


def _project_id(request: Request) -> str | None:
    value = getattr(request.state, "arena_project_id", None)
    return value if isinstance(value, str) else None


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise ForgeError("invalid_json", "A JSON object is required.") from exc
    if not isinstance(body, dict):
        raise ForgeError("invalid_json", "A JSON object is required.")
    return body


def _forge(request: Request) -> ForgeService:
    service = getattr(request.app.state, "forge_service", None)
    if not isinstance(service, ForgeService):
        raise ForgeError("forge_unavailable", "Arena Forge is not configured for this deployment.", status_code=503)
    return service


def _planner(request: Request) -> ExperimentPlannerService:
    service = getattr(request.app.state, "experiment_planner_service", None)
    if not isinstance(service, ExperimentPlannerService):
        raise ForgeError("planner_unavailable", "The experiment planner is not configured for this deployment.", status_code=503)
    return service


def _safety(request: Request) -> ProcessSafetyService:
    service = getattr(request.app.state, "process_safety_service", None)
    if not isinstance(service, ProcessSafetyService):
        raise ForgeError("process_safety_unavailable", "Process-safety controls are not configured for this deployment.", status_code=503)
    return service


def _error(exc: ForgeError) -> JSONResponse:
    return public_service_error(exc)


@router.post("/forge/proposals")
async def create_proposal(request: Request):
    try:
        return _forge(request).create_proposal(await _body(request), project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)


@router.get("/forge/proposals/{proposal_digest}")
async def get_proposal(proposal_digest: str, request: Request):
    try:
        return _forge(request).proposal(proposal_digest, project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)


@router.post("/forge/proposals/{proposal_digest}/approval")
async def approve_proposal(proposal_digest: str, request: Request):
    try:
        return _forge(request).approve(proposal_digest, await _body(request), project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)


@router.post("/forge/evaluations")
async def create_evaluation(request: Request):
    try:
        return _forge(request).create_evaluation(await _body(request), project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)


@router.get("/forge/evolution-receipts/{receipt_digest}")
@router.get("/forge/receipts/{receipt_digest}")
async def get_evolution_receipt(receipt_digest: str, request: Request):
    try:
        return _forge(request).receipt(receipt_digest, project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)


@router.post("/experiment-plans/next-best")
@router.post("/forge/next-best-experiments")
async def create_next_best_experiment(request: Request):
    try:
        return _planner(request).create(await _body(request), project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)


@router.get("/experiment-plans/{report_digest}")
@router.get("/forge/next-best-experiments/{report_digest}")
async def get_next_best_experiment(report_digest: str, request: Request):
    try:
        return _planner(request).report(report_digest, project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)


@router.post("/process-safety-reports")
@router.post("/forge/process-safety")
async def create_process_safety_report(request: Request):
    try:
        return _safety(request).create(await _body(request), project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)


@router.get("/process-safety-reports/{report_digest}")
@router.get("/forge/process-safety/{report_digest}")
async def get_process_safety_report(report_digest: str, request: Request):
    try:
        return _safety(request).report(report_digest, project_id=_project_id(request))
    except ForgeError as exc:
        return _error(exc)
