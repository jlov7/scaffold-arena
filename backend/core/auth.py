from __future__ import annotations

from fastapi import Header, HTTPException

from config.settings import settings


def verify_token(authorization: str | None = Header(default=None)) -> None:
    """Verify bearer token for protected endpoints.

    If API_SECRET_KEY is unset, auth is disabled for local/dev convenience.
    """
    if not settings.api_secret_key:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.api_secret_key:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
