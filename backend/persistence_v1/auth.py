"""Durable, token-free persistence primitives for the team auth boundary."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update

from .repository import ArenaRepository
from .schema import (
    auth_sessions,
    identity_users,
    oidc_login_transactions,
    project_memberships,
    team_audit_events,
    team_settings,
)


def _id() -> str:
    return uuid.uuid4().hex


class AuthRepository:
    """Separate persistence prevents legacy project-local user semantics leaking."""

    def __init__(self, arena: ArenaRepository):
        self.arena = arena

    def create_login_transaction(self, *, state_digest: str, browser_binding_digest: str, nonce: str, code_verifier: str, redirect_uri: str, expires_at: datetime) -> None:
        with self.arena.transaction(immediate=True) as conn:
            conn.execute(insert(oidc_login_transactions).values(id=_id(), state_digest=state_digest, browser_binding_digest=browser_binding_digest, nonce=nonce, code_verifier=code_verifier, redirect_uri=redirect_uri, expires_at=expires_at))

    def consume_login_transaction(self, state_digest: str, browser_binding_digest: str, now: datetime) -> Mapping[str, Any] | None:
        with self.arena.transaction(immediate=True) as conn:
            row = conn.execute(select(oidc_login_transactions).where(oidc_login_transactions.c.state_digest == state_digest, oidc_login_transactions.c.browser_binding_digest == browser_binding_digest, oidc_login_transactions.c.consumed_at.is_(None), oidc_login_transactions.c.expires_at > now)).mappings().first()
            if row is None:
                return None
            consumed = conn.execute(
                update(oidc_login_transactions)
                .where(
                    oidc_login_transactions.c.id == row["id"],
                    oidc_login_transactions.c.browser_binding_digest == browser_binding_digest,
                    oidc_login_transactions.c.consumed_at.is_(None),
                    oidc_login_transactions.c.expires_at > now,
                )
                .values(consumed_at=now)
            )
            if consumed.rowcount != 1:
                return None
            return dict(row)

    def upsert_identity(self, *, issuer: str, subject: str, email: str | None, display_name: str | None) -> str:
        with self.arena.transaction(immediate=True) as conn:
            identity_id = conn.execute(select(identity_users.c.id).where(identity_users.c.issuer == issuer, identity_users.c.subject == subject)).scalar_one_or_none()
            if identity_id is not None:
                conn.execute(update(identity_users).where(identity_users.c.id == identity_id).values(email=email, display_name=display_name))
                return str(identity_id)
            identity_id = _id()
            conn.execute(insert(identity_users).values(id=identity_id, issuer=issuer, subject=subject, email=email, display_name=display_name))
            return identity_id

    def create_session(self, *, token_digest: str, identity_user_id: str, csrf_token: str, expires_at: datetime, rotated_from_id: str | None = None) -> str:
        session_id = _id()
        with self.arena.transaction(immediate=True) as conn:
            if rotated_from_id:
                conn.execute(update(auth_sessions).where(auth_sessions.c.id == rotated_from_id).values(revoked_at=datetime.now(UTC)))
            conn.execute(insert(auth_sessions).values(id=session_id, token_digest=token_digest, identity_user_id=identity_user_id, csrf_token=csrf_token, expires_at=expires_at, rotated_from_id=rotated_from_id))
        return session_id

    def session(self, token_digest: str, now: datetime) -> Mapping[str, Any] | None:
        with self.arena.transaction() as conn:
            row = conn.execute(select(
                auth_sessions.c.id.label("session_id"), auth_sessions.c.identity_user_id,
                auth_sessions.c.csrf_token, auth_sessions.c.expires_at,
                identity_users.c.issuer, identity_users.c.subject, identity_users.c.email,
                identity_users.c.display_name,
            ).join(identity_users, identity_users.c.id == auth_sessions.c.identity_user_id).where(auth_sessions.c.token_digest == token_digest, auth_sessions.c.revoked_at.is_(None), auth_sessions.c.expires_at > now)).mappings().first()
            if row is not None:
                conn.execute(update(auth_sessions).where(auth_sessions.c.id == row["session_id"]).values(last_seen_at=now))
            return None if row is None else dict(row)

    def revoke_session(self, token_digest: str, now: datetime) -> None:
        with self.arena.transaction(immediate=True) as conn:
            conn.execute(update(auth_sessions).where(auth_sessions.c.token_digest == token_digest, auth_sessions.c.revoked_at.is_(None)).values(revoked_at=now))

    def membership(self, identity_user_id: str, project_id: str) -> str | None:
        with self.arena.engine.connect() as conn:
            role = conn.execute(select(project_memberships.c.role).where(project_memberships.c.identity_user_id == identity_user_id, project_memberships.c.project_id == project_id)).scalar_one_or_none()
            return None if role is None else str(role)

    def memberships(self, identity_user_id: str) -> list[dict[str, str]]:
        with self.arena.engine.connect() as conn:
            return [dict(row) for row in conn.execute(select(project_memberships.c.project_id, project_memberships.c.role).where(project_memberships.c.identity_user_id == identity_user_id)).mappings().all()]

    def set_membership(self, project_id: str, identity_user_id: str, role: str) -> None:
        if role not in {"admin", "operator", "reviewer", "viewer"}:
            raise ValueError("invalid team role")
        with self.arena.transaction(immediate=True) as conn:
            existing = conn.execute(select(project_memberships.c.project_id).where(project_memberships.c.project_id == project_id, project_memberships.c.identity_user_id == identity_user_id)).scalar_one_or_none()
            if existing is None:
                conn.execute(insert(project_memberships).values(project_id=project_id, identity_user_id=identity_user_id, role=role))
            else:
                conn.execute(update(project_memberships).where(project_memberships.c.project_id == project_id, project_memberships.c.identity_user_id == identity_user_id).values(role=role))

    def project_settings(self, project_id: str) -> dict[str, Any]:
        with self.arena.engine.connect() as conn:
            row = conn.execute(select(team_settings).where(team_settings.c.project_id == project_id)).mappings().first()
            return {} if row is None else dict(row)

    def update_project_settings(self, project_id: str, actor_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        if set(values) - {"retention_days"}:
            raise ValueError("unsupported settings field")
        retention_days = values.get("retention_days")
        if retention_days is not None and (not isinstance(retention_days, int) or isinstance(retention_days, bool) or not 1 <= retention_days <= 3650):
            raise ValueError("retention_days must be an integer between 1 and 3650")
        with self.arena.transaction(immediate=True) as conn:
            exists = conn.execute(select(team_settings.c.project_id).where(team_settings.c.project_id == project_id)).scalar_one_or_none()
            values = {"retention_days": retention_days, "updated_by_identity_user_id": actor_id}
            if exists is None:
                conn.execute(insert(team_settings).values(project_id=project_id, **values))
            else:
                conn.execute(update(team_settings).where(team_settings.c.project_id == project_id).values(**values))
        return self.project_settings(project_id)

    def audit(self, *, request_id: str, event_type: str, project_id: str | None = None, identity_user_id: str | None = None, method: str | None = None, path: str | None = None, payload: Mapping[str, Any] | None = None) -> None:
        with self.arena.transaction() as conn:
            conn.execute(insert(team_audit_events).values(id=_id(), request_id=request_id, project_id=project_id, identity_user_id=identity_user_id, event_type=event_type, method=method, path=path, payload=dict(payload or {})))
