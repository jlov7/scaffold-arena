from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_liveness_readiness_and_metrics_are_truthful_and_redacted(tmp_path: Path, monkeypatch) -> None:
    from config.settings import settings
    from main import app

    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(settings, "protocol_v1_database_url", f"sqlite:///{tmp_path / 'protocol.db'}")
    monkeypatch.setattr(settings, "protocol_v1_artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "protocol_v1_deployment_profile", "personal")

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "alive"}
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["dependencies"]["artifact_store"] == "local_initialized"
        assert "bucket policy" in ready.json()["claim_ceiling"]
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "scaffold_arena_http_requests_total" in metrics.text
        assert str(tmp_path) not in metrics.text


def test_team_local_artifact_override_returns_readiness_hold() -> None:
    from main import app

    app.state.protocol_runtime_ready = True
    from config.settings import settings

    original_profile = settings.protocol_v1_deployment_profile
    original_backend = settings.protocol_v1_artifact_backend
    original_override = settings.protocol_v1_team_allow_local_artifacts_development
    original_verified = getattr(app.state, "protocol_artifact_connectivity_verified", False)
    try:
        settings.protocol_v1_deployment_profile = "team"
        settings.protocol_v1_artifact_backend = "local"
        settings.protocol_v1_team_allow_local_artifacts_development = True
        response = TestClient(app, raise_server_exceptions=False).get("/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "HOLD"
    finally:
        settings.protocol_v1_deployment_profile = original_profile
        settings.protocol_v1_artifact_backend = original_backend
        settings.protocol_v1_team_allow_local_artifacts_development = original_override
        app.state.protocol_artifact_connectivity_verified = original_verified


def test_team_s3_readiness_requires_verified_connectivity() -> None:
    from config.settings import settings
    from main import app

    original_profile = settings.protocol_v1_deployment_profile
    original_backend = settings.protocol_v1_artifact_backend
    original_verified = getattr(app.state, "protocol_artifact_connectivity_verified", False)
    original_runtime_ready = getattr(app.state, "protocol_runtime_ready", False)
    try:
        settings.protocol_v1_deployment_profile = "team"
        settings.protocol_v1_artifact_backend = "s3_compatible"
        app.state.protocol_runtime_ready = True
        app.state.protocol_artifact_connectivity_verified = False
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/ready").json()["reason"] == "artifact_connectivity_unverified"
        app.state.protocol_artifact_connectivity_verified = True
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["dependencies"]["artifact_store"] == "connectivity_verified"
        assert "bucket policy" in ready.json()["claim_ceiling"]
    finally:
        settings.protocol_v1_deployment_profile = original_profile
        settings.protocol_v1_artifact_backend = original_backend
        app.state.protocol_artifact_connectivity_verified = original_verified
        app.state.protocol_runtime_ready = original_runtime_ready
