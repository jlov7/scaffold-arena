from __future__ import annotations

import hashlib
import json
import time

from fastapi import HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from config.models import all_models_meta
from config.settings import settings
from core.budget import DailyBudgetExceededError, budget_tracker
from core.registry import all_scaffolds_meta, all_tasks_meta

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

_IDEMPOTENCY_TTL_SECONDS = 60 * 60
_idempotency_cache: dict[str, dict] = {}


def extract_llm_api_key(request: Request) -> str | None:
    raw = request.headers.get("x-llm-api-key")
    return raw.strip() if raw and raw.strip() else None


def available_task_ids() -> list[str]:
    return sorted(task["id"] for task in all_tasks_meta())


def available_model_ids() -> list[str]:
    return sorted(model["id"] for model in all_models_meta())


def available_scaffold_ids() -> list[str]:
    return sorted(scaffold["id"] for scaffold in all_scaffolds_meta())


def validate_task_id(task_id: str) -> None:
    if task_id not in available_task_ids():
        raise HTTPException(
            status_code=400,
            detail="Unknown task.",
        )


def validate_model_id(model_id: str) -> None:
    if model_id not in available_model_ids():
        raise HTTPException(
            status_code=400,
            detail="Unknown model.",
        )


def validate_scaffold_ids(scaffold_ids: list[str]) -> None:
    valid = set(available_scaffold_ids())
    for scaffold_id in scaffold_ids:
        if scaffold_id not in valid:
            raise HTTPException(
                status_code=400,
                detail="Unknown scaffold.",
            )


def validate_budget_for_new_run() -> None:
    try:
        budget_tracker.check_new_run_allowed(daily_budget_usd=settings.daily_budget_usd)
    except DailyBudgetExceededError as exc:
        raise HTTPException(status_code=429, detail="Daily run budget is exhausted.") from exc


def _prune_idempotency_cache() -> None:
    now = time.time()
    for key, entry in list(_idempotency_cache.items()):
        if now - float(entry.get("ts", 0)) >= _IDEMPOTENCY_TTL_SECONDS:
            _idempotency_cache.pop(key, None)


def idempotency_fingerprint(payload: dict, llm_api_key: str | None) -> str:
    normalized = {"payload": payload, "llm_api_key_present": bool(llm_api_key)}
    as_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(as_json.encode("utf-8")).hexdigest()


def lookup_idempotent_response(idempotency_key: str, fingerprint: str) -> dict | None:
    _prune_idempotency_cache()
    cached = _idempotency_cache.get(idempotency_key)
    if not cached:
        return None
    if cached.get("fingerprint") != fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was reused with a different request payload.",
        )
    response = dict(cached.get("response", {}))
    response["idempotent_replay"] = True
    return response


def store_idempotent_response(
    idempotency_key: str,
    fingerprint: str,
    response_payload: dict,
) -> None:
    _idempotency_cache[idempotency_key] = {
        "fingerprint": fingerprint,
        "response": dict(response_payload),
        "ts": time.time(),
    }
