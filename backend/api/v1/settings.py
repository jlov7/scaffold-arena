"""Truthful deployment readiness, with a deliberately tiny non-secret settings allowlist."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from auth_v1 import AuthPrincipal, AuthService
from config.settings import settings
from persistence_v1.schema import identity_users, project_memberships

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-settings"])


def _service(request: Request) -> AuthService | None:
    value = getattr(request.app.state, "auth_service", None)
    return value if isinstance(value, AuthService) else None


def _readiness(request: Request) -> dict[str, Any]:
    runtime = getattr(request.app.state, "protocol_registry_runtime", None)
    return {
        "deployment_profile": settings.protocol_v1_deployment_profile,
        "storage": {"configured": bool(settings.resolved_protocol_v1_database_url), "kind": "postgresql" if settings.resolved_protocol_v1_database_url.startswith("postgres") else "sqlite", "team_ready": settings.protocol_v1_is_team_mode and settings.protocol_v1_database_url.startswith("postgres")},
        "authentication": {"mode": "oidc_server_session" if settings.protocol_v1_is_team_mode else "none_personal", "configured": settings.protocol_v1_is_team_mode and _service(request) is not None},
        "adapters": {"configured": bool(getattr(runtime, "adapter_registry", None)), "provider_started": False},
        "budget": {"max_cost_per_run_usd": settings.max_cost_per_run_usd, "daily_budget_usd": settings.daily_budget_usd},
        "retention": {"status": "PASS_ARCHIVAL_ONLY", "reason": "Admin-only, recovery-bound archival is available; full project and artifact deletion remain intentionally unavailable because immutable evidence and shared content-addressed bytes are retained."},
        "secrets": {"exposed": False, "source": "environment_or_external_secret_reference_only"},
    }


@router.get("/settings")
async def get_settings(request: Request):
    return _readiness(request)


@router.patch("/settings")
@router.post("/settings")
async def update_settings(request: Request):
    if not settings.protocol_v1_is_team_mode:
        return JSONResponse(status_code=405, content={"error": {"code": "personal_mode_read_only", "message": "Personal deployment settings are not mutable through this API."}})
    principal = getattr(request.state, "auth_principal", None)
    service = _service(request)
    project_id = request.headers.get("x-arena-project-id")
    if not isinstance(principal, AuthPrincipal) or service is None or not project_id:
        return JSONResponse(status_code=401, content={"error": {"code": "authentication_required", "message": "An authenticated project administrator is required."}})
    try:
        body = await request.json()
        if not isinstance(body, Mapping):
            raise TypeError("settings body must be an object")
        changed = service.repository.update_project_settings(project_id, principal.identity_user_id, body)
    except (ValueError, TypeError):
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_settings", "message": "The settings request cannot be processed."}})
    service.repository.audit(request_id=str(getattr(request.state, "request_id", "unknown")), event_type="settings.changed", project_id=project_id, identity_user_id=principal.identity_user_id, payload={"fields": sorted(body)})
    return {"settings": changed, "retention": {"status": "PASS_ARCHIVAL_ONLY", "reason": "A changed retention period applies only through a separately previewed, confirmed, grace-delayed archival plan; full project deletion remains unavailable."}}


@router.get("/projects/{project_id}/memberships")
async def list_memberships(project_id: str, request: Request):
    """Expose the identity directory only to a project administrator."""
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"error": {"code": "auth_unavailable", "message": "Team authentication is unavailable."}})
    if request.headers.get("x-arena-project-id") != project_id:
        return JSONResponse(status_code=400, content={"error": {"code": "project_mismatch", "message": "Project header must match the requested memberships."}})
    if getattr(request.state, "arena_role", None) != "admin":
        return JSONResponse(status_code=403, content={"error": {"code": "role_forbidden", "message": "Only project administrators can view membership identities."}})
    with service.repository.arena.engine.connect() as conn:
        rows = conn.execute(select(project_memberships.c.role, identity_users.c.issuer, identity_users.c.subject, identity_users.c.email, identity_users.c.display_name).join(identity_users, identity_users.c.id == project_memberships.c.identity_user_id).where(project_memberships.c.project_id == project_id)).mappings().all()
    return {"project_id": project_id, "memberships": [dict(row) for row in rows]}


@router.put("/projects/{project_id}/memberships")
async def set_membership(project_id: str, request: Request):
    if not settings.protocol_v1_is_team_mode:
        return JSONResponse(status_code=405, content={"error": {"code": "personal_mode_read_only", "message": "Personal mode has no team memberships."}})
    principal = getattr(request.state, "auth_principal", None)
    service = _service(request)
    if not isinstance(principal, AuthPrincipal) or service is None or request.headers.get("x-arena-project-id") != project_id:
        return JSONResponse(status_code=403, content={"error": {"code": "membership_admin_required", "message": "An authenticated administrator for this project is required."}})
    if service.repository.membership(principal.identity_user_id, project_id) != "admin":
        return JSONResponse(status_code=403, content={"error": {"code": "role_forbidden", "message": "Only project administrators can change memberships."}})
    try:
        body = await request.json()
        if not isinstance(body, Mapping) or set(body) - {"issuer", "subject", "email", "display_name", "role"}:
            raise TypeError("membership body must contain only issuer, subject, optional profile fields, and role")
        issuer, subject, role = body.get("issuer"), body.get("subject"), body.get("role")
        if not all(isinstance(value, str) and value.strip() for value in (issuer, subject, role)):
            raise ValueError("membership issuer, subject, and role are required strings")
        identity_id = service.repository.upsert_identity(issuer=issuer.strip(), subject=subject.strip(), email=body.get("email") if isinstance(body.get("email"), str) else None, display_name=body.get("display_name") if isinstance(body.get("display_name"), str) else None)
        service.repository.set_membership(project_id, identity_id, role.strip())
    except (TypeError, ValueError):
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_membership", "message": "The membership request cannot be processed."}})
    service.repository.audit(request_id=str(getattr(request.state, "request_id", "unknown")), event_type="membership.changed", project_id=project_id, identity_user_id=principal.identity_user_id, payload={"issuer": issuer.strip(), "subject": subject.strip(), "role": role.strip()})
    return {"project_id": project_id, "issuer": issuer.strip(), "subject": subject.strip(), "role": role.strip()}
