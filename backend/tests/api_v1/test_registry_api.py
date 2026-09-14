from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.registry import router
from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import metadata
from services_v1 import ProtocolRegistryService


def pack_payload() -> dict:
    return {
        "study_pack_id": "pack-one", "version": "1.0.0", "title": "Synthetic Pack", "license_spdx": "MIT",
        "authors": [{"name": "Test"}], "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ["synthetic fixture exploration"], "limitations": ["No provider evidence."],
        "preregistration": {"reference_uri": "synthetic://pre", "content_hash": "a" * 64},
        "scenarios": [{"scenario_id": "scenario-one", "title": "Scenario", "task_family": "extract", "prompt": "Synthetic prompt."}],
        "harnesses": [{"harness_id": "harness-one", "version": "1", "adapter": "recorded"}],
        "experiments": [{"experiment_id": "template-one", "study_pack_id": "pack-one", "scenario_ids": ["scenario-one"], "harness_ids": ["harness-one"], "deterministic_weight": 0.7}],
    }


def test_v1_routes_use_injected_personal_project_and_do_not_replace_v0_routes(tmp_path: Path) -> None:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    app = FastAPI()
    app.state.protocol_registry_service = ProtocolRegistryService(
        repository, LocalArtifactStore(tmp_path / "artifacts"), personal_project_id="personal"
    )
    app.include_router(router)
    client = TestClient(app)

    response = client.post("/api/v1/study-packs/validate", content=json.dumps(pack_payload()), headers={"content-type": "application/json"})
    assert response.status_code == 200
    imported = client.post("/api/v1/study-packs/import", content=json.dumps(pack_payload()), headers={"content-type": "application/json"})
    assert imported.status_code == 200
    assert client.get("/api/v1/study-packs").json()["study_packs"][0]["study_pack_id"] == "pack-one"
    experiment = {
        "experiment_id": "experiment-one",
        "study_pack_id": "pack-one",
        "scenario_ids": ["scenario-one"],
        "harness_ids": ["harness-one"],
        "deterministic_weight": 0.7,
        "owner_approval": "approved",
    }
    assert client.post("/api/v1/experiments", json=experiment).status_code == 200
    draft = client.post("/api/v1/experiments/experiment-one/preflight").json()
    assert "experiment_not_frozen" in {item["code"] for item in draft["blockers"]}
    frozen = client.post("/api/v1/experiments/experiment-one/freeze")
    assert frozen.status_code == 200
    assert frozen.json()["frozen"] is True
    after_freeze = client.post("/api/v1/experiments/experiment-one/preflight").json()
    assert "experiment_not_frozen" not in {item["code"] for item in after_freeze["blockers"]}
    from main import app as main_app

    paths = set(main_app.openapi()["paths"])
    assert "/api/runs" in paths
    assert "/api/runs/{run_id}/events" in paths
    assert "/api/v1/study-packs" in paths


def test_browser_recovery_registry_get_routes_return_canonical_objects_and_errors(tmp_path: Path) -> None:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    app = FastAPI()
    app.state.protocol_registry_service = ProtocolRegistryService(
        repository, LocalArtifactStore(tmp_path / "artifacts"), personal_project_id="personal"
    )
    app.include_router(router)
    client = TestClient(app)
    assert client.post("/api/v1/study-packs/import", content=json.dumps(pack_payload()), headers={"content-type": "application/json"}).status_code == 200
    experiment = {
        "experiment_id": "experiment-one", "study_pack_id": "pack-one", "scenario_ids": ["scenario-one"],
        "harness_ids": ["harness-one"], "deterministic_weight": 0.7, "owner_approval": "approved",
    }
    assert client.post("/api/v1/experiments", json=experiment).status_code == 200
    frozen = client.post("/api/v1/experiments/experiment-one/freeze").json()
    pack = client.get("/api/v1/study-packs/pack-one/versions/1.0.0")
    assert pack.status_code == 200
    assert pack.json()["canonical_study_pack"]["study_pack_id"] == "pack-one"
    listed = client.get("/api/v1/experiments", params={"study_pack_id": "pack-one", "study_pack_version": "1.0.0"})
    assert listed.status_code == 200 and listed.json()["experiments"][0]["experiment_id"] == "experiment-one"
    assert client.get("/api/v1/experiments", params={"study_pack_id": "pack-one", "study_pack_version": "missing"}).json()["experiments"] == []
    detail = client.get("/api/v1/experiments/experiment-one")
    assert detail.status_code == 200
    assert detail.json()["immutable_identity"]["freeze_hash"] == frozen["freeze_hash"]
    assert client.get("/api/v1/experiments/missing").status_code == 404
    assert client.post("/api/v1/experiments").status_code == 400
    assert set(client.app.openapi()["paths"]["/api/v1/experiments"]) == {"get", "post"}


def test_public_openapi_operation_ids_are_unique() -> None:
    from main import app as main_app

    operation_ids = [
        operation["operationId"]
        for path in main_app.openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]

    assert len(operation_ids) == len(set(operation_ids))


def test_api_exposes_service_body_limit_as_structured_413(tmp_path: Path) -> None:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'limited.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    app = FastAPI()
    app.state.protocol_registry_service = ProtocolRegistryService(
        repository,
        LocalArtifactStore(tmp_path / "limited-artifacts"),
        personal_project_id="personal",
        max_body_bytes=32,
    )
    app.include_router(router)
    response = TestClient(app).post(
        "/api/v1/study-packs/validate",
        content=json.dumps(pack_payload()),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "body_too_large"


def test_main_lifespan_bootstraps_protocol_v1_with_durable_local_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config.settings import settings
    from main import app

    legacy_db = tmp_path / "legacy.db"
    protocol_db = tmp_path / "protocol.db"
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(settings, "sqlite_path", str(legacy_db))
    monkeypatch.setattr(settings, "protocol_v1_database_url", f"sqlite:///{protocol_db}")
    monkeypatch.setattr(settings, "protocol_v1_artifact_root", str(artifact_root))
    monkeypatch.setattr(settings, "protocol_v1_personal_project_id", "personal-test")

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        execution_preflight = client.options(
            "/api/v1/experiments/main-experiment/executions",
            headers={
                "origin": "http://localhost:5173",
                "access-control-request-method": "POST",
                "access-control-request-headers": "idempotency-key, x-arena-project-id",
            },
        )
        assert execution_preflight.status_code == 200
        assert {"idempotency-key", "x-arena-project-id"}.issubset(
            set(execution_preflight.headers["access-control-allow-headers"].lower().split(", "))
        )
        event_preflight = client.options(
            "/api/v1/executions/pending/events",
            headers={
                "origin": "http://localhost:5173",
                "access-control-request-method": "GET",
                "access-control-request-headers": "last-event-id, x-arena-project-id",
            },
        )
        assert event_preflight.status_code == 200
        assert {"last-event-id", "x-arena-project-id"}.issubset(
            set(event_preflight.headers["access-control-allow-headers"].lower().split(", "))
        )
        assert client.get("/api/v1/study-packs").json()["study_packs"] == []
        assert client.post(
            "/api/v1/study-packs/validate",
            content=json.dumps(pack_payload()),
            headers={"content-type": "application/json"},
        ).status_code == 200
        assert client.post(
            "/api/v1/study-packs/import",
            content=json.dumps(pack_payload()),
            headers={"content-type": "application/json"},
        ).status_code == 200
        experiment = {
            "experiment_id": "main-experiment",
            "study_pack_id": "pack-one",
            "scenario_ids": ["scenario-one"],
            "harness_ids": ["harness-one"],
            "deterministic_weight": 0.7,
            "owner_approval": "approved",
        }
        assert client.post("/api/v1/experiments", json=experiment).status_code == 200
        assert client.post("/api/v1/experiments/main-experiment/freeze").status_code == 200
        assert client.post("/api/v1/experiments/main-experiment/preflight").status_code == 200
        execution = client.post(
            "/api/v1/experiments/main-experiment/executions",
            json={},
            headers={"idempotency-key": "main-smoke"},
        )
        assert execution.status_code != 503

    assert protocol_db.is_file()
    assert artifact_root.is_dir()

    with TestClient(app) as client:
        assert client.get("/api/v1/study-packs").json()["study_packs"][0]["study_pack_id"] == "pack-one"


def test_main_lifespan_rejects_invalid_protocol_v1_artifact_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config.settings import settings
    from main import app

    artifact_file = tmp_path / "not-a-directory"
    artifact_file.write_text("not a directory")
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(settings, "protocol_v1_database_url", f"sqlite:///{tmp_path / 'protocol.db'}")
    monkeypatch.setattr(settings, "protocol_v1_artifact_root", str(artifact_file))

    with pytest.raises(RuntimeError, match="protocol_v1_artifact_root"), TestClient(app):
        pass


def test_main_lifespan_disposes_protocol_runtime_after_v0_startup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config.settings import settings
    from core import registry as core_registry
    from main import app

    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(settings, "protocol_v1_database_url", f"sqlite:///{tmp_path / 'protocol.db'}")
    monkeypatch.setattr(settings, "protocol_v1_artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(core_registry, "register_task", lambda _task: (_ for _ in ()).throw(RuntimeError("startup failed")))

    with pytest.raises(RuntimeError, match="startup failed"), TestClient(app):
        pass

    assert app.state.protocol_registry_service is None
    assert app.state.execution_api_service is None
