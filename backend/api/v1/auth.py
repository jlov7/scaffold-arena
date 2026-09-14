"""Team-mode authentication endpoints. Personal mode deliberately has no login."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from api.public_errors import public_service_error
from auth_v1 import AuthError, AuthPrincipal, AuthService
from config.settings import settings

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-auth"])
_LOGIN_TRANSACTION_COOKIE = "__Host-arena-login-transaction"


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _service(request: Request) -> AuthService | None:
    service = getattr(request.app.state, "auth_service", None)
    return service if isinstance(service, AuthService) else None


def _error(exc: AuthError) -> JSONResponse:
    return public_service_error(exc)


def _cookie_kwargs() -> dict[str, Any]:
    return {"key": settings.protocol_v1_session_cookie_name, "httponly": True, "secure": settings.protocol_v1_session_cookie_secure, "samesite": settings.protocol_v1_session_cookie_samesite, "path": "/", "max_age": settings.protocol_v1_session_ttl_seconds}


def _login_transaction_cookie_kwargs() -> dict[str, Any]:
    return {"key": _LOGIN_TRANSACTION_COOKIE, "httponly": True, "secure": settings.protocol_v1_session_cookie_secure, "samesite": "lax", "path": "/", "max_age": settings.protocol_v1_oidc_transaction_ttl_seconds}


def _personal_session() -> dict[str, Any]:
    return {"authenticated": True, "mode": "personal", "project_id": settings.protocol_v1_personal_project_id, "authority_ceiling": "personal/local authority only", "login": "not_applicable"}


@router.get("/session")
async def session(request: Request):
    if not settings.protocol_v1_is_team_mode:
        return _personal_session()
    principal = getattr(request.state, "auth_principal", None)
    if not isinstance(principal, AuthPrincipal):
        return JSONResponse(status_code=401, content={"error": {"code": "authentication_required", "message": "A valid team session is required."}})
    service = _service(request)
    assert service is not None
    return {"authenticated": True, "mode": "team", "user": {"issuer": principal.issuer, "subject": principal.subject, "email": principal.email, "display_name": principal.display_name}, "memberships": service.repository.memberships(principal.identity_user_id), "csrf_token": principal.csrf_token, "expires_at": principal.expires_at.isoformat()}


@router.get("/login")
@router.post("/login")
async def login(request: Request):
    if not settings.protocol_v1_is_team_mode:
        return JSONResponse(status_code=404, content={"error": {"code": "personal_mode", "message": "Personal mode has no login flow."}})
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"error": {"code": "auth_unavailable", "message": "Team authentication is unavailable."}})
    try:
        started = await service.start_login(request_id=_request_id(request))
        response = RedirectResponse(started.authorization_url, status_code=302)
        response.set_cookie(value=started.browser_transaction, **_login_transaction_cookie_kwargs())
        return response
    except AuthError as exc:
        return _error(exc)


@router.get("/callback")
async def callback(request: Request, state: str = "", code: str = ""):
    service = _service(request)
    if not settings.protocol_v1_is_team_mode or service is None:
        return JSONResponse(status_code=404, content={"error": {"code": "team_auth_unavailable", "message": "Team authentication is not configured."}})
    try:
        token, _principal = await service.complete_login(state=state, code=code, browser_transaction=request.cookies.get(_LOGIN_TRANSACTION_COOKIE), request_id=_request_id(request), prior_cookie=request.cookies.get(settings.protocol_v1_session_cookie_name))
    except AuthError as exc:
        response = _error(exc)
        response.delete_cookie(key=_LOGIN_TRANSACTION_COOKIE, path="/")
        return response
    response = JSONResponse(status_code=200, content={"authenticated": True, "mode": "team"})
    response.set_cookie(value=token, **_cookie_kwargs())
    response.delete_cookie(key=_LOGIN_TRANSACTION_COOKIE, path="/")
    return response


@router.post("/logout")
async def logout(request: Request):
    if not settings.protocol_v1_is_team_mode:
        return _personal_session()
    service = _service(request)
    if service is None:
        return JSONResponse(status_code=503, content={"error": {"code": "auth_unavailable", "message": "Team authentication is unavailable."}})
    principal = getattr(request.state, "auth_principal", None)
    service.logout(request.cookies.get(settings.protocol_v1_session_cookie_name), request_id=_request_id(request), actor_id=principal.identity_user_id if isinstance(principal, AuthPrincipal) else None)
    response = JSONResponse(status_code=200, content={"authenticated": False})
    response.delete_cookie(key=settings.protocol_v1_session_cookie_name, path="/")
    return response
