from __future__ import annotations

import logging
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api import autopsy, comparison, metadata, operational, reporting, runs
from api.deps import _idempotency_cache, limiter, settings
from api.v1 import router as protocol_v1_router
from config.settings import settings as protocol_settings
from core.logging_setup import setup_logging
from core.run_engine import (
    cancel_active_runs,
    start_arena_run,
    start_patch_rerun,
    wait_for_run_completion,
)
from core.storage import init_db
from services_v1 import (
    OfflineDemoService,
    initialize_protocol_registry,
    register_current_scaffold_components,
)
from services_v1.offline_demo_runtime import local_offline_demo_capability_enabled

logger = logging.getLogger(__name__)

__all__ = ["_idempotency_cache", "app"]


async def _start_legacy_arena_run(*args, **kwargs) -> None:
    await start_arena_run(*args, **kwargs)


async def _start_legacy_patch_rerun(*args, **kwargs) -> None:
    await start_patch_rerun(*args, **kwargs)


runs.configure_run_starters(
    arena_run_starter=_start_legacy_arena_run,
    patch_rerun_starter=_start_legacy_patch_rerun,
)


@asynccontextmanager
async def lifespan(application: FastAPI):
    setup_logging()
    init_db()
    limiter._storage.reset()
    application.state.operational_metrics = Counter()
    application.state.protocol_runtime_ready = False
    protocol_runtime = await initialize_protocol_registry(settings)
    application.state.protocol_registry_service = protocol_runtime.service
    application.state.execution_api_service = protocol_runtime.execution_service
    application.state.study_pack_export_service = protocol_runtime.export_service
    application.state.evidence_service = protocol_runtime.evidence_service
    application.state.review_service = protocol_runtime.review_service
    application.state.analysis_service = protocol_runtime.analysis_service
    application.state.decision_service = protocol_runtime.decision_service
    application.state.trace_lab_service = protocol_runtime.trace_lab_service
    application.state.genome_service = protocol_runtime.genome_service
    application.state.xray_service = protocol_runtime.xray_service
    application.state.observatory_service = protocol_runtime.observatory_service
    application.state.counterfactual_replay_service = protocol_runtime.counterfactual_replay_service
    application.state.harness_ci_service = protocol_runtime.harness_ci_service
    application.state.forge_service = protocol_runtime.forge_service
    application.state.experiment_planner_service = protocol_runtime.experiment_planner_service
    application.state.process_safety_service = protocol_runtime.process_safety_service
    application.state.protocol_registry_runtime = protocol_runtime
    application.state.auth_service = protocol_runtime.auth_service
    application.state.protocol_artifact_connectivity_verified = protocol_runtime.artifact_connectivity_verified
    application.state.protocol_runtime_ready = True
    application.state.offline_demo_service = None
    application.state.offline_demo_unavailable_reason = (
        "Start the local workbench with `arena serve --enable-offline-demo` on a literal loopback address."
    )
    if not protocol_settings.protocol_v1_is_team_mode and local_offline_demo_capability_enabled():
        application.state.offline_demo_service = await OfflineDemoService.create(
            protocol_runtime.service.repository,
            protocol_runtime.artifact_store,
            protocol_runtime.service,
            personal_project_id=settings.protocol_v1_personal_project_id.strip(),
            repository_root=Path(__file__).resolve().parents[1],
            enabled=True,
        )
        application.state.offline_demo_unavailable_reason = None
    try:
        register_current_scaffold_components()
        logger.info("startup_complete")
        yield
    finally:
        try:
            cancelled = cancel_active_runs()
            drained = await wait_for_run_completion(timeout_s=10.0)
        finally:
            offline_demo = getattr(application.state, "offline_demo_service", None)
            if isinstance(offline_demo, OfflineDemoService):
                await offline_demo.close()
            application.state.offline_demo_service = None
            application.state.offline_demo_unavailable_reason = None
            protocol_runtime.close()
            application.state.protocol_registry_service = None
            application.state.execution_api_service = None
            application.state.study_pack_export_service = None
            application.state.evidence_service = None
            application.state.review_service = None
            application.state.analysis_service = None
            application.state.decision_service = None
            application.state.trace_lab_service = None
            application.state.genome_service = None
            application.state.xray_service = None
            application.state.observatory_service = None
            application.state.counterfactual_replay_service = None
            application.state.harness_ci_service = None
            application.state.forge_service = None
            application.state.experiment_planner_service = None
            application.state.process_safety_service = None
            application.state.protocol_registry_runtime = None
            application.state.auth_service = None
            application.state.protocol_runtime_ready = False
            application.state.protocol_artifact_connectivity_verified = False
        logger.info(
            "shutdown_complete", extra={"cancelled_runs": cancelled, "drained": drained}
        )


app = FastAPI(title="Scaffold Arena", version="0.9.1", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


def _metric_scope(path: str) -> str:
    if path in {"/health", "/ready", "/build-meta", "/metrics", "/api/health"}:
        return "operational"
    if path.startswith("/api/v1"):
        return "protocol_v1"
    return "legacy"


@app.middleware("http")
async def collect_operational_metrics(request: Request, call_next):
    response = await call_next(request)
    metrics = getattr(request.app.state, "operational_metrics", None)
    if isinstance(metrics, Counter):
        metrics[(request.method, _metric_scope(request.url.path), f"{response.status_code // 100}xx")] += 1
    return response


def _team_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def _required_role(path: str, method: str) -> str:
    if path.endswith("/memberships"):
        return "admin"
    if path.startswith("/api/v1/forge/proposals/") and path.endswith("/approval"):
        return "admin"
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "viewer"
    if path == "/api/v1/settings":
        return "admin"
    if "/retention/" in path and method not in {"GET", "HEAD", "OPTIONS"}:
        return "admin"
    if "/annotation-batches/" in path and path.endswith(("/annotations", "/adjudications")):
        return "reviewer"
    return "operator"


_ROLE_RANK = {"viewer": 0, "reviewer": 1, "operator": 2, "admin": 3}


@app.middleware("http")
async def enforce_protocol_v1_team_authorization(request: Request, call_next):
    """Fail closed before any team-scoped service can resolve a project."""
    request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    path = request.url.path
    if not protocol_settings.protocol_v1_is_team_mode:
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request.state.request_id)
        return response
    if path.startswith("/api/") and not path.startswith("/api/v1"):
        response = _team_error(
            404,
            "legacy_api_disabled",
            "Legacy API routes are disabled in team mode.",
        )
        response.headers.setdefault("X-Request-ID", request.state.request_id)
        return response
    if not path.startswith("/api/v1"):
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request.state.request_id)
        return response
    public_paths = {"/api/v1/login", "/api/v1/callback"}
    if path in public_paths:
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request.state.request_id)
        return response
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        return _team_error(503, "auth_unavailable", "Team authorization was not initialized.")
    principal = service.principal(request.cookies.get(protocol_settings.protocol_v1_session_cookie_name))
    if principal is None:
        return _team_error(401, "authentication_required", "A valid team session is required.")
    request.state.auth_principal = principal
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-arena-csrf") != principal.csrf_token:
        return _team_error(403, "csrf_invalid", "A valid X-Arena-CSRF token is required for mutating requests.")
    project_id = request.headers.get("x-arena-project-id")
    # Session and settings readiness are account-scoped. Settings writes must
    # identify a project, and all workbench routes always require one.
    project_optional = path in {"/api/v1/session", "/api/v1/logout", "/api/v1/settings"} and request.method in {"GET", "HEAD"}
    if not project_id and not project_optional:
        return _team_error(400, "project_required", "X-Arena-Project-ID is required in team mode.")
    role: str | None = None
    if project_id:
        role = service.repository.membership(principal.identity_user_id, project_id)
        if role is None:
            return _team_error(403, "project_membership_required", "The requested project is not in this session's memberships.")
        request.state.arena_project_id = project_id
        request.state.arena_role = role
    required_role = _required_role(path, request.method)
    if role is not None and _ROLE_RANK[role] < _ROLE_RANK[required_role]:
        return _team_error(403, "role_forbidden", "This role cannot perform the requested team operation.")
    if path == "/api/v1/settings" and request.method not in {"GET", "HEAD"} and role != "admin":
        return _team_error(403, "role_forbidden", "Only project administrators can change settings.")
    response = await call_next(request)
    response.headers.setdefault("X-Request-ID", request.state.request_id)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        # The event deliberately excludes body, query parameters, cookies,
        # authorization headers, and provider credentials.
        service.repository.audit(request_id=request.state.request_id, event_type="v1.request_mutated", project_id=project_id, identity_user_id=principal.identity_user_id, method=request.method, path=path, payload={"status_code": response.status_code, "role": role})
    return response


@app.exception_handler(RateLimitExceeded)
async def _custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    response = _rate_limit_exceeded_handler(request, exc)
    response.headers.setdefault("Retry-After", "60")
    return response


origins = [
    origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "Last-Event-ID",
        "X-Arena-Project-ID",
        "X-Arena-CSRF",
        "X-LLM-API-Key",
    ],
)


def _is_production_env() -> bool:
    return settings.app_env.strip().lower() in {"prod", "production"}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if _is_production_env():
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"
        )
    return response


@app.middleware("http")
async def enforce_request_size_limits(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_size_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": f"Request body too large (> {settings.max_request_size_bytes} bytes)"
                        },
                    )
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid Content-Length header"
                )
        body = await request.body()
        if len(body) > settings.max_request_size_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"Request body too large (> {settings.max_request_size_bytes} bytes)"
                },
            )

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(request.scope, receive)
    return await call_next(request)


app.include_router(metadata.router)
app.include_router(operational.router)
app.include_router(runs.router)
app.include_router(comparison.router)
app.include_router(autopsy.router)
app.include_router(reporting.router)
app.include_router(protocol_v1_router)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def build_spa_asset_index(static_root: Path) -> dict[str, Path]:
    """Index regular files that resolve inside static_root."""
    root = static_root.resolve()
    assets: dict[str, Path] = {}
    for entry in root.rglob("*"):
        resolved = entry.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_file():
            assets[relative.as_posix()] = resolved
    return assets


def resolve_spa_asset(asset_index: dict[str, Path], full_path: str) -> Path | None:
    """Resolve a requested SPA asset by exact lookup in the startup index."""
    requested = unquote(full_path)
    if not requested or requested.startswith(("/", "\\")) or "\\" in requested:
        return None
    if any(part in {"", ".", ".."} for part in requested.split("/")):
        return None
    return asset_index.get(requested)

if _STATIC_DIR.is_dir():
    _STATIC_ASSETS = build_spa_asset_index(_STATIC_DIR)
    app.mount(
        "/assets", StaticFiles(directory=_STATIC_DIR / "assets", follow_symlink=False), name="static-assets"
    )

    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str):
        file_path = resolve_spa_asset(_STATIC_ASSETS, full_path)
        if file_path is not None:
            return FileResponse(file_path)
        return FileResponse(_STATIC_DIR / "index.html")
