"""Recoverable, project-scoped retention.  It intentionally does not delete projects."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, insert, or_, select, update

from artifacts_v1 import ArtifactIntegrityError
from auth_v1 import AuthPrincipal, AuthService
from persistence_v1.schema import (
    artifacts,
    deletion_plans,
    deletion_tombstones,
    idempotency_records,
    metadata,
    projects,
    team_settings,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/retention", tags=["protocol-v1-retention"])

_CEILING = (
    "Project archival and expiration of recoverable idempotency records only; "
    "projects, immutable evidence, team audit history, tombstones, and all artifact bytes are never deleted."
)
_EXCLUDED = ("projects", "immutable evidence receipts and reports", "team audit history", "tombstones", "artifact registry and content-addressed bytes")


def _service(request: Request) -> AuthService | None:
    value = getattr(request.app.state, "auth_service", None)
    return value if isinstance(value, AuthService) else None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value.tzinfo else value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _confirmation(snapshot_digest: str) -> str:
    return hashlib.sha256(f"scaffold-arena-retention-confirm-v1:{snapshot_digest}".encode("ascii")).hexdigest()


def _project_export(service: AuthService, project_id: str, *, connection: Any | None = None) -> dict[str, Any]:
    """Export project-reachable relational rows without traversing global artifacts/identities."""
    arena = service.repository.arena
    if connection is None:
        with arena.engine.connect() as conn:
            return _project_export(service, project_id, connection=conn)
    conn = connection
    excluded = {"artifacts", "identity_users", "auth_sessions", "oidc_login_transactions", "price_catalog", "team_audit_events", "deletion_plans", "deletion_tombstones"}
    rows: dict[str, dict[str, dict[str, Any]]] = {}
    known: dict[str, set[Any]] = {"projects": {project_id}}
    project = conn.execute(select(projects).where(projects.c.id == project_id)).mappings().first()
    if project is None:
        raise LookupError("project_not_found")
    rows["projects"] = {project_id: dict(project)}
    for _ in range(len(metadata.tables) + 1):
        changed = False
        for name, table in metadata.tables.items():
            if name in excluded:
                continue
            conditions = []
            if "project_id" in table.c:
                conditions.append(table.c.project_id == project_id)
            for foreign_key in table.foreign_keys:
                target = foreign_key.column.table.name
                values = known.get(target, set())
                if values:
                    conditions.append(foreign_key.parent.in_(values))
            if not conditions:
                continue
            selected = conn.execute(select(table).where(or_(*conditions))).mappings().all()
            if not selected:
                continue
            bucket = rows.setdefault(name, {})
            for row in selected:
                key = "|".join(str(row[column.name]) for column in table.primary_key.columns)
                if key in bucket:
                    continue
                plain = dict(row)
                bucket[key] = plain
                for column in table.primary_key.columns:
                    known.setdefault(name, set()).add(plain[column.name])
                changed = True
        if not changed:
            break
    retained_rows = {name: [bucket[key] for key in sorted(bucket)] for name, bucket in sorted(rows.items())}
    return {"format": "scaffold-arena-retention-export-v1", "project_id": project_id, "rows": retained_rows, "immutable_exclusions": list(_EXCLUDED), "claim_ceiling": _CEILING}


def _preview(service: AuthService, project_id: str) -> dict[str, Any]:
    export = _project_export(service, project_id)
    snapshot_digest = _digest(export)
    settings = service.repository.project_settings(project_id)
    retention_days = settings.get("retention_days")
    now = datetime.now(UTC)
    eligible = 0
    if isinstance(retention_days, int):
        with service.repository.arena.engine.connect() as conn:
            eligible = len(conn.execute(select(idempotency_records.c.id).where(idempotency_records.c.project_id == project_id, idempotency_records.c.created_at < now - timedelta(days=retention_days))).all())
    return {"project_id": project_id, "snapshot_digest": snapshot_digest, "confirmation_token": _confirmation(snapshot_digest), "retention_days": retention_days, "eligible_purge": {"idempotency_records": eligible, "artifact_bytes": 0}, "immutable_exclusions": list(_EXCLUDED), "claim_ceiling": _CEILING}


def _principal(request: Request, project_id: str) -> tuple[AuthService, AuthPrincipal] | JSONResponse:
    service = _service(request)
    principal = getattr(request.state, "auth_principal", None)
    if service is None or not isinstance(principal, AuthPrincipal):
        return _error(401, "authentication_required", "An authenticated project member is required.")
    if request.headers.get("x-arena-project-id") != project_id:
        return _error(400, "project_mismatch", "Project header must match the retention route.")
    return service, principal


@router.get("/preview")
async def preview(project_id: str, request: Request):
    resolved = _principal(request, project_id)
    if isinstance(resolved, JSONResponse):
        return resolved
    service, _ = resolved
    try:
        return _preview(service, project_id)
    except LookupError:
        return _error(404, "project_not_found", "The requested project does not exist.")


@router.get("/plans")
async def plans(project_id: str, request: Request):
    resolved = _principal(request, project_id)
    if isinstance(resolved, JSONResponse):
        return resolved
    service, _ = resolved
    with service.repository.arena.engine.connect() as conn:
        values = [dict(row) for row in conn.execute(select(deletion_plans).where(deletion_plans.c.project_id == project_id).order_by(deletion_plans.c.created_at.desc())).mappings()]
    return {"project_id": project_id, "plans": [_canonical(value) for value in values], "claim_ceiling": _CEILING}


@router.post("/plans")
async def schedule(project_id: str, request: Request):
    resolved = _principal(request, project_id)
    if isinstance(resolved, JSONResponse):
        return resolved
    service, principal = resolved
    if getattr(request.state, "arena_role", None) != "admin":
        return _error(403, "role_forbidden", "Only project administrators can schedule retention.")
    try:
        body = await request.json()
        if not isinstance(body, Mapping) or set(body) - {"snapshot_digest", "confirmation_token", "grace_seconds"}:
            raise ValueError("body must contain snapshot_digest, confirmation_token, and optional grace_seconds")
        snapshot_digest, token = body.get("snapshot_digest"), body.get("confirmation_token")
        grace = body.get("grace_seconds", 3600)
        if not isinstance(snapshot_digest, str) or not isinstance(token, str) or not isinstance(grace, int) or isinstance(grace, bool) or not 60 <= grace <= 2_592_000:
            raise ValueError("invalid retention schedule confirmation or grace period")
        current = _preview(service, project_id)
        if snapshot_digest != current["snapshot_digest"] or token != current["confirmation_token"]:
            return _error(409, "preview_stale_or_tampered", "The preview no longer matches the current project state and confirmation token.")
    except (TypeError, ValueError):
        return _error(422, "invalid_retention_plan", "The retention plan request cannot be processed.")
    now = datetime.now(UTC)
    plan_id = uuid.uuid4().hex
    with service.repository.arena.transaction(immediate=True) as conn:
        conn.execute(insert(deletion_plans).values(id=plan_id, project_id=project_id, state="scheduled", snapshot_digest=snapshot_digest, confirmation_digest=_confirmation(snapshot_digest), grace_seconds=grace, due_at=now + timedelta(seconds=grace), scheduled_by_identity_user_id=principal.identity_user_id))
    service.repository.audit(request_id=str(getattr(request.state, "request_id", "unknown")), event_type="retention.scheduled", project_id=project_id, identity_user_id=principal.identity_user_id, payload={"plan_id": plan_id, "snapshot_digest": snapshot_digest, "grace_seconds": grace})
    return {"plan_id": plan_id, "state": "scheduled", "due_at": _canonical(now + timedelta(seconds=grace)), "claim_ceiling": _CEILING}


@router.post("/plans/{plan_id}/cancel")
async def cancel(project_id: str, plan_id: str, request: Request):
    resolved = _principal(request, project_id)
    if isinstance(resolved, JSONResponse):
        return resolved
    service, principal = resolved
    if getattr(request.state, "arena_role", None) != "admin":
        return _error(403, "role_forbidden", "Only project administrators can cancel retention.")
    now = datetime.now(UTC)
    with service.repository.arena.transaction(immediate=True) as conn:
        changed = conn.execute(update(deletion_plans).where(deletion_plans.c.id == plan_id, deletion_plans.c.project_id == project_id, deletion_plans.c.state == "scheduled", deletion_plans.c.due_at > now).values(state="cancelled", cancelled_at=now, cancelled_by_identity_user_id=principal.identity_user_id)).rowcount
    if changed != 1:
        return _error(409, "plan_not_cancellable", "Only a scheduled plan before its due time can be cancelled.")
    service.repository.audit(request_id=str(getattr(request.state, "request_id", "unknown")), event_type="retention.cancelled", project_id=project_id, identity_user_id=principal.identity_user_id, payload={"plan_id": plan_id})
    return {"plan_id": plan_id, "state": "cancelled"}


@router.post("/plans/{plan_id}/execute")
async def execute(project_id: str, plan_id: str, request: Request):
    resolved = _principal(request, project_id)
    if isinstance(resolved, JSONResponse):
        return resolved
    service, principal = resolved
    if getattr(request.state, "arena_role", None) != "admin":
        return _error(403, "role_forbidden", "Only project administrators can execute retention.")
    runtime = getattr(request.app.state, "protocol_registry_runtime", None)
    store = getattr(runtime, "artifact_store", None)
    if not callable(getattr(store, "put_bytes", None)) or not callable(getattr(store, "get_bytes", None)) or not callable(getattr(store, "uri_for", None)):
        return _error(503, "artifact_store_unavailable", "Retention fails closed until the configured artifact store is available.")
    now = datetime.now(UTC)
    with service.repository.arena.engine.connect() as conn:
        plan = conn.execute(select(deletion_plans).where(deletion_plans.c.id == plan_id, deletion_plans.c.project_id == project_id)).mappings().first()
    if plan is None:
        return _error(404, "plan_not_found", "The retention plan does not exist in this project.")
    if plan["state"] != "scheduled" or _utc(plan["due_at"]) > now:
        return _error(409, "plan_not_due", "Only a scheduled plan at or after its due time can execute.")
    if plan["confirmation_digest"] != _confirmation(str(plan["snapshot_digest"])):
        return _error(409, "plan_confirmation_invalid", "The persisted plan confirmation is invalid; no records were purged.")
    try:
        export = _project_export(service, project_id)
        if _digest(export) != plan["snapshot_digest"]:
            with service.repository.arena.transaction(immediate=True) as conn:
                conn.execute(update(deletion_plans).where(deletion_plans.c.id == plan_id, deletion_plans.c.state == "scheduled").values(state="blocked"))
            return _error(409, "plan_state_mismatch", "Project state changed after preview; the plan was blocked without deleting data.")
        raw = _bytes(export)
        manifest_digest = store.put_bytes(raw, media_type="application/json", metadata={"classification": "retention_recovery_export_v1"})
        if store.get_bytes(manifest_digest) != raw:
            raise ArtifactIntegrityError("export artifact readback mismatch")
    except (ArtifactIntegrityError, FileNotFoundError, ValueError):
        return _error(409, "recovery_export_invalid", "Retention stopped before deletion because the recovery export could not be verified.")
    with service.repository.arena.transaction(immediate=True) as conn:
        # This row lock is effective on PostgreSQL; SQLite's immediate transaction
        # supplies its single-writer equivalent. Every destructive predicate is
        # rechecked from this same connection and transaction snapshot.
        locked = conn.execute(select(deletion_plans).where(deletion_plans.c.id == plan_id, deletion_plans.c.project_id == project_id).with_for_update()).mappings().first()
        if locked is None:
            return _error(404, "plan_not_found", "The retention plan does not exist in this project.")
        if locked["state"] != "scheduled" or _utc(locked["due_at"]) > now:
            return _error(409, "plan_not_due", "Only a scheduled plan at or after its due time can execute.")
        if locked["confirmation_digest"] != _confirmation(str(locked["snapshot_digest"])):
            conn.execute(update(deletion_plans).where(deletion_plans.c.id == plan_id).values(state="blocked"))
            return _error(409, "plan_confirmation_invalid", "The persisted plan confirmation is invalid; no records were purged.")
        current = _digest(_project_export(service, project_id, connection=conn))
        if current != locked["snapshot_digest"]:
            conn.execute(update(deletion_plans).where(deletion_plans.c.id == plan_id).values(state="blocked"))
            return _error(409, "plan_state_mismatch", "Project state changed before execution; no records were purged.")
        retention_days = conn.execute(select(team_settings.c.retention_days).where(team_settings.c.project_id == project_id)).scalar_one_or_none()
        if not isinstance(retention_days, int):
            return _error(409, "retention_days_required", "Set a project retention_days value before executing a plan.")
        existing = conn.execute(select(artifacts.c.size_bytes, artifacts.c.storage_uri).where(artifacts.c.digest == manifest_digest)).mappings().first()
        if existing is None:
            conn.execute(insert(artifacts).values(digest=manifest_digest, size_bytes=len(raw), storage_uri=store.uri_for(manifest_digest), media_type="application/json", metadata_json={"classification": "retention_recovery_export_v1"}))
        elif existing["size_bytes"] != len(raw) or existing["storage_uri"] != store.uri_for(manifest_digest):
            return _error(409, "recovery_export_invalid", "The registered recovery export does not match verified storage; no records were purged.")
        cutoff = now - timedelta(days=retention_days)
        purged = conn.execute(delete(idempotency_records).where(idempotency_records.c.project_id == project_id, idempotency_records.c.created_at < cutoff)).rowcount
        changed = conn.execute(update(deletion_plans).where(deletion_plans.c.id == plan_id, deletion_plans.c.state == "scheduled", deletion_plans.c.due_at <= now).values(state="executed", executed_at=now, executed_by_identity_user_id=principal.identity_user_id, purged_idempotency_records=purged)).rowcount
        if changed != 1:
            return _error(409, "plan_execution_raced", "The plan changed concurrently; no additional records were purged.")
        conn.execute(insert(deletion_tombstones).values(id=uuid.uuid4().hex, project_id=project_id, plan_id=plan_id, snapshot_digest=locked["snapshot_digest"], export_manifest_digest=manifest_digest, purged_idempotency_records=purged, claim_ceiling=_CEILING, executed_by_identity_user_id=principal.identity_user_id))
    service.repository.audit(request_id=str(getattr(request.state, "request_id", "unknown")), event_type="retention.executed", project_id=project_id, identity_user_id=principal.identity_user_id, payload={"plan_id": plan_id, "export_manifest_digest": manifest_digest, "purged_idempotency_records": purged})
    return {"plan_id": plan_id, "state": "executed", "export_manifest_digest": manifest_digest, "purged": {"idempotency_records": purged, "artifact_bytes": 0}, "claim_ceiling": _CEILING}
