"""Provider-free Counterfactual Replay and Harness CI API boundary."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.public_errors import public_service_error
from services_v1.counterfactual import CounterfactualError, CounterfactualReplayService, HarnessCIError, HarnessCIService


router = APIRouter(prefix="/api/v1", tags=["counterfactual-replay-v1"])


def _project_id(request: Request) -> str | None:
    value = getattr(request.state, "arena_project_id", None)
    return value if isinstance(value, str) else None


def _replays(request: Request) -> CounterfactualReplayService:
    service = getattr(request.app.state, "counterfactual_replay_service", None)
    if not isinstance(service, CounterfactualReplayService):
        raise CounterfactualError("counterfactual_unavailable", "Counterfactual replay services are not configured for this deployment.", status_code=503)
    return service


def _ci(request: Request) -> HarnessCIService:
    service = getattr(request.app.state, "harness_ci_service", None)
    if not isinstance(service, HarnessCIService):
        raise HarnessCIError("harness_ci_unavailable", "Harness CI services are not configured for this deployment.", status_code=503)
    return service


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception as exc:
        raise CounterfactualError("invalid_json", "A JSON object is required.") from exc
    if not isinstance(body, dict):
        raise CounterfactualError("invalid_json", "A JSON object is required.")
    return body


def _error(exc: CounterfactualError) -> JSONResponse:
    return public_service_error(exc)


@router.post("/counterfactual-replays")
@router.post("/counterfactual/replays", include_in_schema=False)
async def create_counterfactual_replay(request: Request):
    try:
        return _replays(request).create(await _body(request), project_id=_project_id(request))
    except CounterfactualError as exc:
        return _error(exc)


@router.get("/counterfactual-replays/{report_digest}")
@router.get("/counterfactual/replays/{report_digest}", include_in_schema=False)
async def get_counterfactual_replay(report_digest: str, request: Request):
    try:
        return _replays(request).report(report_digest, project_id=_project_id(request))
    except CounterfactualError as exc:
        return _error(exc)


@router.post("/harness-ci/checks")
@router.post("/harness-ci-reports")
async def create_harness_ci_report(request: Request):
    try:
        return _ci(request).create(await _body(request), project_id=_project_id(request))
    except CounterfactualError as exc:
        return _error(exc)


@router.get("/harness-ci/checks/{report_digest}")
@router.get("/harness-ci-reports/{report_digest}")
async def get_harness_ci_report(report_digest: str, request: Request):
    try:
        return _ci(request).report(report_digest, project_id=_project_id(request))
    except CounterfactualError as exc:
        return _error(exc)
