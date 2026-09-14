from __future__ import annotations

import re

_STATUS_RE = re.compile(r"\b([45]\d{2})\b")


def _status_code(message: str) -> int | None:
    match = _STATUS_RE.search(message)
    if not match:
        return None
    status = int(match.group(1))
    return status if 400 <= status <= 599 else None


def _suffix(status: int | None) -> str:
    return f" ({status})" if status else ""


def sanitize_provider_error(error: Exception | str) -> str:
    raw = str(error).strip()
    if not raw:
        return "Provider request failed. Retry after checking provider settings."

    lower = raw.lower()
    status = _status_code(raw)
    looks_auth_related = (
        status in {401, 403}
        or "api_key" in lower
        or "api key" in lower
        or "x-api-key" in lower
        or "authentication" in lower
        or "authorization" in lower
    )

    if looks_auth_related:
        if any(marker in lower for marker in ("required", "missing", "not set")):
            return (
                "Provider key missing. Set a valid provider key in Settings or "
                "backend environment, then retry."
            )
        return (
            f"Provider key rejected{_suffix(status)}. Update the model provider key "
            "in Settings or backend environment, then retry."
        )

    if status == 429:
        return "Provider rate limit hit (429). Wait, then retry."
    if status is not None and status >= 500:
        return f"Provider request failed{_suffix(status)}. Retry shortly."

    return "Provider request could not be completed. Check provider settings and retry."


def was_provider_error_sanitized(error: Exception | str) -> bool:
    raw = str(error).strip()
    return sanitize_provider_error(error) != raw
