from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from build_meta import build_metadata
from config.settings import settings as protocol_settings

router = APIRouter(tags=["operational"])


@router.get("/health", include_in_schema=False)
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/build-meta", include_in_schema=False)
async def public_build_metadata(response: Response) -> dict[str, str]:
    """Expose non-secret build identity outside authenticated product APIs."""

    response.headers["Cache-Control"] = "no-store"
    return build_metadata()


@router.get("/ready", include_in_schema=False)
async def readiness(request: Request):
    if not getattr(request.app.state, "protocol_runtime_ready", False):
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "protocol_runtime_unavailable"},
        )
    artifact_readiness = protocol_settings.protocol_v1_team_artifact_readiness
    if artifact_readiness == "HOLD_DEVELOPMENT_LOCAL_ARTIFACTS":
        return JSONResponse(
            status_code=503,
            content={
                "status": "HOLD",
                "dependencies": {
                    "database": "initialized",
                    "artifact_store": artifact_readiness,
                },
                "claim_ceiling": "development-only local artifact override is not team deployment readiness",
            },
        )
    if artifact_readiness == "CONFIGURED_NOT_PROBED" and not getattr(
        request.app.state, "protocol_artifact_connectivity_verified", False
    ):
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "artifact_connectivity_unverified"},
        )
    artifact_dependency = (
        "local_initialized"
        if artifact_readiness == "PERSONAL_LOCAL"
        else "connectivity_verified"
    )
    return {
        "status": "ready",
        "dependencies": {
            "database": "initialized",
            "artifact_store": artifact_dependency,
        },
        "claim_ceiling": "readiness verifies object storage connectivity only, not bucket policy or encryption assurance",
    }


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> PlainTextResponse:
    values = getattr(request.app.state, "operational_metrics", Counter())
    lines = ["# TYPE scaffold_arena_http_requests_total counter"]
    for (method, scope, status), value in sorted(values.items()):
        lines.append(
            "scaffold_arena_http_requests_total"
            f'{{method="{method}",scope="{scope}",status="{status}"}} {value}'
        )
    return PlainTextResponse(
        "\n".join(lines) + "\n", media_type="text/plain; version=0.0.4"
    )
