"""Stable, non-diagnostic error responses for public API boundaries."""

from __future__ import annotations

import re
from typing import Any

from fastapi.responses import JSONResponse

_PUBLIC_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_MESSAGE_BY_STATUS = {
    400: "The request is invalid.",
    401: "Authentication is required.",
    403: "The request is not permitted.",
    404: "The requested resource was not found.",
    409: "The operation cannot proceed in its current state.",
    413: "The request is too large.",
    422: "The request cannot be processed.",
    429: "Too many requests. Retry later.",
    500: "The request could not be completed.",
    502: "The service is temporarily unavailable.",
    503: "The service is temporarily unavailable.",
    504: "The service is temporarily unavailable.",
}


def public_service_error(error: Any) -> JSONResponse:
    """Return only a stable code, status, and static public message.

    Service exceptions may retain diagnostic text for server-side logging, but
    public HTTP payloads must never serialize that text.
    """
    status = getattr(error, "status_code", 500)
    status = status if isinstance(status, int) and 400 <= status <= 599 else 500
    candidate = getattr(error, "code", "internal_error")
    code = candidate if isinstance(candidate, str) and _PUBLIC_CODE.fullmatch(candidate) else "internal_error"
    content: dict[str, Any] = {
        "error": {
            "code": code,
            "message": _MESSAGE_BY_STATUS.get(status, "The request could not be completed."),
        }
    }
    if status == 409:
        content["verdict"] = "HOLD"
    return JSONResponse(status_code=status, content=content)
