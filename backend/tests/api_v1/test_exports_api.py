from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.analysis import router as analysis_router
from api.v1.exports import router
from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import metadata
from services_v1 import ProtocolRegistryService, StudyPackExportService
from tests.services_v1.test_analysis_service import _configuration, _service


def _pack() -> dict:
    return {
        "study_pack_id": "pack-one",
        "version": "1.0.0",
        "title": "Synthetic Pack",
        "license_spdx": "MIT",
        "authors": [{"name": "Test"}],
        "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ["synthetic fixture exploration"],
        "limitations": ["No provider evidence."],
        "preregistration": {
            "reference_uri": "synthetic://pre",
            "content_hash": "a" * 64,
        },
        "scenarios": [
            {
                "scenario_id": "scenario-one",
                "title": "Scenario",
                "task_family": "extract",
                "prompt": "Synthetic prompt.",
            }
        ],
        "harnesses": [
            {"harness_id": "harness-one", "version": "1", "adapter": "recorded"}
        ],
        "experiments": [
            {
                "experiment_id": "template-one",
                "study_pack_id": "pack-one",
                "scenario_ids": ["scenario-one"],
                "harness_ids": ["harness-one"],
                "deterministic_weight": 0.7,
            }
        ],
    }


def _client(tmp_path: Path) -> TestClient:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    repository.create_project("Other", project_id="other")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    registry = ProtocolRegistryService(
        repository, artifacts, personal_project_id="personal"
    )
    registry.import_pack(
        json.dumps(_pack()).encode(), "application/json", project_id="personal"
    )
    app = FastAPI()
    app.state.study_pack_export_service = StudyPackExportService(
        repository, artifacts, personal_project_id="personal"
    )
    app.include_router(router)
    return TestClient(app)


def test_post_export_requires_explicit_study_pack_discriminant_and_downloads(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/v1/exports",
        json={"kind": "study_pack", "study_pack_id": "pack-one", "version": "1.0.0"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="study-pack-pack-one-1.0.0.zip"'
    )
    assert response.headers["x-study-pack-content-digest"]
    assert response.headers["x-study-pack-manifest-hash"]
    assert response.content.startswith(b"PK")
    assert (
        client.post(
            "/api/v1/exports", json={"study_pack_id": "pack-one", "version": "1.0.0"}
        ).status_code
        == 400
    )


def test_post_export_is_project_scoped_and_fail_closed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/v1/exports",
        json={"kind": "study_pack", "study_pack_id": "pack-one", "version": "1.0.0"},
        headers={"x-arena-project-id": "other"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "study_pack_not_found"


def test_analysis_csv_export_is_report_bound_and_regenerable(tmp_path: Path) -> None:
    service, execution_id = _service(tmp_path)
    app = FastAPI()
    app.state.analysis_service = service
    app.include_router(analysis_router)
    app.include_router(router)
    client = TestClient(app)
    analyzed = client.post("/api/v1/analysis", headers={"x-arena-project-id": "personal"}, json={
        "experiment_id": "experiment-one", "execution_id": execution_id,
        "analysis_config": _configuration(),
    })
    assert analyzed.status_code == 200
    report_digest = analyzed.json()["report_digest"]
    request = {"kind": "analysis", "report_digest": report_digest, "format": "csv"}
    first = client.post("/api/v1/exports", headers={"x-arena-project-id": "personal"}, json=request)
    second = client.post("/api/v1/exports", headers={"x-arena-project-id": "personal"}, json=request)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.headers["x-analysis-report-digest"] == report_digest
    assert first.headers["x-analysis-manifest-hash"] == second.headers["x-analysis-manifest-hash"]
    assert first.content.startswith(b"report_digest,record_type")
    parquet = client.post("/api/v1/exports", headers={"x-arena-project-id": "personal"}, json={
        "kind": "analysis", "report_digest": report_digest, "format": "parquet",
    })
    assert parquet.status_code == 200
    assert parquet.content[:4] == parquet.content[-4:] == b"PAR1"
