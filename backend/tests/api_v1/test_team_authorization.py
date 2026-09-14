from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_team_mode_disables_legacy_api_routes(monkeypatch) -> None:
    with TestClient(main.app) as client:
        monkeypatch.setattr(main.protocol_settings, "protocol_v1_deployment_profile", "team")
        for path in (
            "/api/runs",
            "/api/runs/run-id",
            "/api/runs/run-id/events",
            "/api/runs/run-id/diagnostics",
            "/api/stats",
            "/api/meta",
        ):
            response = client.get(path)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "legacy_api_disabled"


def test_membership_directory_requires_admin_role() -> None:
    assert main._required_role("/api/v1/projects/project/memberships", "GET") == "admin"
    assert main._required_role("/api/v1/projects/project/memberships", "PUT") == "admin"
