from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update

from artifacts_v1 import LocalArtifactStore
from auth_v1 import AuthService
from config.settings import Settings
from config.settings import settings as runtime_settings
from main import app
from persistence_v1 import (
    ArenaRepository,
    AuthRepository,
    create_persistence_engine,
    metadata,
)
from persistence_v1.schema import (
    artifacts,
    deletion_plans,
    deletion_tombstones,
    evidence_receipts,
    idempotency_records,
)


def _team_client(tmp_path: Path, monkeypatch):
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'retention.db'}")
    metadata.create_all(engine)
    arena = ArenaRepository(engine)
    arena.create_project("Retention", project_id="project")
    auth_repository = AuthRepository(arena)
    configured = Settings(
        protocol_v1_deployment_profile="team", protocol_v1_database_url="postgresql://example.invalid/arena",
        protocol_v1_oidc_issuer="https://issuer.example", protocol_v1_oidc_client_id="client",
        protocol_v1_oidc_redirect_uri="https://arena.example/api/v1/callback",
        protocol_v1_oidc_allowed_redirect_uris="https://arena.example/api/v1/callback",
        protocol_v1_session_secret="x" * 32, protocol_v1_session_cookie_secure=True,
    )
    service = AuthService(auth_repository, configured)
    admin_id = auth_repository.upsert_identity(issuer="https://issuer.example", subject="admin", email=None, display_name="Admin")
    viewer_id = auth_repository.upsert_identity(issuer="https://issuer.example", subject="viewer", email=None, display_name="Viewer")
    operator_id = auth_repository.upsert_identity(issuer="https://issuer.example", subject="operator", email=None, display_name="Operator")
    for identity_id, role in ((admin_id, "admin"), (viewer_id, "viewer"), (operator_id, "operator")):
        auth_repository.set_membership("project", identity_id, role)
    auth_repository.update_project_settings("project", admin_id, {"retention_days": 1})

    def session(identity_id: str) -> tuple[str, str]:
        raw = f"token-{identity_id}"
        csrf = f"csrf-{identity_id}"
        auth_repository.create_session(token_digest=service._session_digest(raw), identity_user_id=identity_id, csrf_token=csrf, expires_at=datetime.now(UTC) + timedelta(hours=1))
        return raw, csrf

    admin, admin_csrf = session(admin_id)
    viewer, viewer_csrf = session(viewer_id)
    operator, operator_csrf = session(operator_id)
    for field, value in {
        "protocol_v1_deployment_profile": "team",
        "protocol_v1_session_cookie_name": configured.protocol_v1_session_cookie_name,
    }.items():
        monkeypatch.setattr(runtime_settings, field, value)
    monkeypatch.setattr(app.state, "auth_service", service, raising=False)
    monkeypatch.setattr(app.state, "protocol_registry_runtime", SimpleNamespace(artifact_store=LocalArtifactStore(tmp_path / "artifacts")), raising=False)
    client = TestClient(app, raise_server_exceptions=False)

    def headers(token: str, csrf: str | None = None) -> dict[str, str]:
        values = {"x-arena-project-id": "project", "cookie": f"{configured.protocol_v1_session_cookie_name}={token}"}
        if csrf is not None:
            values["x-arena-csrf"] = csrf
        return values

    return client, arena, headers, (admin, admin_csrf), (viewer, viewer_csrf), (operator, operator_csrf)


def test_retention_team_workflow_is_csrf_bound_recoverable_and_archival_only(tmp_path: Path, monkeypatch) -> None:
    client, arena, headers, admin, viewer, operator = _team_client(tmp_path, monkeypatch)
    preview = client.get("/api/v1/projects/project/retention/preview", headers=headers(*viewer))
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["eligible_purge"]["artifact_bytes"] == 0
    assert "artifact bytes" in payload["claim_ceiling"]

    # The real application middleware, not the endpoint itself, rejects missing CSRF.
    missing_csrf = client.post("/api/v1/projects/project/retention/plans", json={"snapshot_digest": payload["snapshot_digest"], "confirmation_token": payload["confirmation_token"]}, headers=headers(admin[0]))
    assert missing_csrf.status_code == 403 and missing_csrf.json()["error"]["code"] == "csrf_invalid"
    for principal in (viewer, operator):
        denied = client.post("/api/v1/projects/project/retention/plans", json={"snapshot_digest": payload["snapshot_digest"], "confirmation_token": payload["confirmation_token"]}, headers=headers(*principal))
        assert denied.status_code == 403
    tampered = client.post("/api/v1/projects/project/retention/plans", json={"snapshot_digest": "0" * 64, "confirmation_token": payload["confirmation_token"]}, headers=headers(*admin))
    assert tampered.status_code == 409 and tampered.json()["error"]["code"] == "preview_stale_or_tampered"

    scheduled = client.post("/api/v1/projects/project/retention/plans", json={"snapshot_digest": payload["snapshot_digest"], "confirmation_token": payload["confirmation_token"], "grace_seconds": 60}, headers=headers(*admin))
    assert scheduled.status_code == 200
    plan_id = scheduled.json()["plan_id"]
    assert client.post(f"/api/v1/projects/project/retention/plans/{plan_id}/execute", headers=headers(*admin)).status_code == 409
    assert client.post(f"/api/v1/projects/project/retention/plans/{plan_id}/cancel", headers=headers(*admin)).json()["state"] == "cancelled"

    fresh = client.get("/api/v1/projects/project/retention/preview", headers=headers(*admin)).json()
    plan = client.post("/api/v1/projects/project/retention/plans", json={"snapshot_digest": fresh["snapshot_digest"], "confirmation_token": fresh["confirmation_token"], "grace_seconds": 60}, headers=headers(*admin)).json()["plan_id"]
    old = datetime.now(UTC) - timedelta(days=3)
    with arena.transaction(immediate=True) as conn:
        conn.execute(insert(idempotency_records).values(id="expired", project_id="project", key="expired", request_digest="a" * 64, response={}, created_at=old))
        conn.execute(insert(artifacts).values(digest="b" * 64, size_bytes=1, storage_uri="test://immutable", media_type="application/json", metadata_json={}))
        conn.execute(insert(evidence_receipts).values(id="receipt", artifact_digest="b" * 64, receipt_kind="fixture", claims=[], project_id="project"))
        # The post-preview mutation is deliberately detected and blocks execution.
        conn.execute(update(deletion_plans).where(deletion_plans.c.id == plan).values(due_at=datetime.now(UTC) - timedelta(seconds=1)))
    blocked = client.post(f"/api/v1/projects/project/retention/plans/{plan}/execute", headers=headers(*admin))
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "plan_state_mismatch"

    final_preview = client.get("/api/v1/projects/project/retention/preview", headers=headers(*admin)).json()
    invalid_plan = client.post("/api/v1/projects/project/retention/plans", json={"snapshot_digest": final_preview["snapshot_digest"], "confirmation_token": final_preview["confirmation_token"], "grace_seconds": 60}, headers=headers(*admin)).json()["plan_id"]
    with arena.transaction(immediate=True) as conn:
        conn.execute(update(deletion_plans).where(deletion_plans.c.id == invalid_plan).values(confirmation_digest="0" * 64, due_at=datetime.now(UTC) - timedelta(seconds=1)))
    invalid = client.post(f"/api/v1/projects/project/retention/plans/{invalid_plan}/execute", headers=headers(*admin))
    assert invalid.status_code == 409 and invalid.json()["error"]["code"] == "plan_confirmation_invalid"

    final_plan = client.post("/api/v1/projects/project/retention/plans", json={"snapshot_digest": final_preview["snapshot_digest"], "confirmation_token": final_preview["confirmation_token"], "grace_seconds": 60}, headers=headers(*admin)).json()["plan_id"]
    with arena.transaction(immediate=True) as conn:
        conn.execute(update(deletion_plans).where(deletion_plans.c.id == final_plan).values(due_at=datetime.now(UTC) - timedelta(seconds=1)))
    executed = client.post(f"/api/v1/projects/project/retention/plans/{final_plan}/execute", headers=headers(*admin))
    assert executed.status_code == 200
    second = client.post(f"/api/v1/projects/project/retention/plans/{final_plan}/execute", headers=headers(*admin))
    assert second.status_code == 409
    with arena.engine.connect() as conn:
        tombstone = conn.execute(select(deletion_tombstones).where(deletion_tombstones.c.plan_id == final_plan)).mappings().one()
        assert tombstone["export_manifest_digest"] == executed.json()["export_manifest_digest"]
        assert conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == "b" * 64)).scalar_one() == "b" * 64
        assert conn.execute(select(evidence_receipts.c.id).where(evidence_receipts.c.id == "receipt")).scalar_one() == "receipt"
        assert conn.execute(select(idempotency_records.c.id).where(idempotency_records.c.id == "expired")).scalar_one_or_none() is None
