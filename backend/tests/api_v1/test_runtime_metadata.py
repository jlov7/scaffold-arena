from __future__ import annotations

from fastapi.testclient import TestClient

import main
from build_meta import ENVIRONMENT_KEYS, SHA_ENVIRONMENT_KEYS


def _clear_build_environment(monkeypatch) -> None:
    for key in (*SHA_ENVIRONMENT_KEYS, *ENVIRONMENT_KEYS, "SOURCE_DATE_EPOCH", "BUILD_TIME"):
        monkeypatch.delenv(key, raising=False)


def test_public_build_metadata_is_non_secret_and_available_in_team_mode(monkeypatch) -> None:
    expected_sha = "a" * 40
    _clear_build_environment(monkeypatch)
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", expected_sha)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")

    with TestClient(main.app) as client:
        monkeypatch.setattr(main.protocol_settings, "protocol_v1_deployment_profile", "team")

        response = client.get("/build-meta")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {
            "schema_version": "build-meta.v1",
            "app_version": "0.9.1",
            "protocol_version": "1.0",
            "git_sha": expected_sha,
            "build_environment": "production",
            "build_time": "unknown",
        }
        assert set(response.json()) == {
            "schema_version",
            "app_version",
            "protocol_version",
            "git_sha",
            "build_environment",
            "build_time",
        }

        legacy = client.get("/api/build-meta")
        assert legacy.status_code == 404
        assert legacy.json()["error"]["code"] == "legacy_api_disabled"


def test_public_build_metadata_reports_unknown_revision_instead_of_partial_sha(monkeypatch) -> None:
    _clear_build_environment(monkeypatch)
    monkeypatch.setenv("GITHUB_SHA", "abc123")

    with TestClient(main.app) as client:
        response = client.get("/build-meta")

        assert response.status_code == 200
        assert response.json()["git_sha"] == "dev"


def test_build_metadata_is_classified_as_operational_telemetry() -> None:
    assert main._metric_scope("/build-meta") == "operational"


def test_cors_preflight_allows_documented_patch_and_put_mutations(monkeypatch) -> None:
    origin = main.settings.cors_origins.split(",")[0].strip()
    monkeypatch.setattr(main.protocol_settings, "protocol_v1_deployment_profile", "personal")

    with TestClient(main.app) as client:
        for method in ("PATCH", "PUT"):
            response = client.options(
                "/api/v1/settings",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type,x-arena-csrf,x-arena-project-id",
                },
            )
            assert response.status_code == 200
            assert method in response.headers["access-control-allow-methods"]
            assert response.headers["access-control-allow-origin"] == origin
