from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update

from api.v1.analysis import router
from persistence_v1.schema import analysis_reports, executions
from tests.services_v1.test_analysis_service import _configuration, _service


def _request(execution_id: str) -> dict:
    return {
        "experiment_id": "experiment-one",
        "execution_id": execution_id,
        "analysis_config": _configuration(),
    }


def _client(service) -> TestClient:
    app = FastAPI()
    app.state.analysis_service = service
    app.include_router(router)
    return TestClient(app)


def test_analysis_api_is_project_scoped_and_never_accepts_caller_evidence(
    tmp_path,
) -> None:
    service, execution_id = _service(tmp_path)
    client = _client(service)
    request = _request(execution_id)
    response = client.post(
        "/api/v1/analysis", headers={"x-arena-project-id": "personal"}, json=request
    )
    assert response.status_code == 200
    assert response.json()["artifact_ref"].startswith("sha256:")
    forged = {**request, "attempts": []}
    rejected = client.post(
        "/api/v1/analysis", headers={"x-arena-project-id": "personal"}, json=forged
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "invalid_analysis_request"
    isolated = client.post(
        "/api/v1/analysis", headers={"x-arena-project-id": "other"}, json=request
    )
    assert isolated.status_code == 404


def test_analysis_report_reads_return_verified_canonical_report_and_summary(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    client = _client(service)
    empty = client.get(
        "/api/v1/analysis-reports", headers={"x-arena-project-id": "personal"}
    )
    assert empty.status_code == 200
    assert empty.json()["analysis_reports"] == []
    created = client.post(
        "/api/v1/analysis", headers={"x-arena-project-id": "personal"}, json=_request(execution_id)
    )
    assert created.status_code == 200
    digest = created.json()["report_digest"]

    listed = client.get("/api/v1/analysis-reports", headers={"x-arena-project-id": "personal"})
    assert listed.status_code == 200
    summary = listed.json()["analysis_reports"]
    assert len(summary) == 1
    assert summary[0]["report_digest"] == digest
    assert summary[0]["adequacy"] == created.json()["adequacy"]
    assert "report" not in summary[0]
    by_experiment = client.get(
        "/api/v1/analysis-reports?experiment_id=experiment-one",
        headers={"x-arena-project-id": "personal"},
    )
    assert by_experiment.status_code == 200
    assert len(by_experiment.json()["analysis_reports"]) == 1

    detail = client.get(
        f"/api/v1/analysis-reports/{digest}", headers={"x-arena-project-id": "personal"}
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["report_digest"] == digest
    assert body["report"]["experiment_id"] == "experiment-one"
    assert body["report"]["exclusions"] == []
    assert body["report"]["profiles"][0]["pass_at_1"]["denominator"] == 1
    assert body["adequacy"] == body["report"]["adequacy"]
    assert body["source_digests"]["input_digest"] == body["binding"]["input_digest"]
    assert body["integrity_not_truth"] is True
    unknown = client.get(
        f"/api/v1/analysis-reports/{'0' * 64}",
        headers={"x-arena-project-id": "personal"},
    )
    assert unknown.status_code == 404


def test_analysis_report_reads_are_idempotent_scoped_and_paginated(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    client = _client(service)
    first = client.post(
        "/api/v1/analysis", headers={"x-arena-project-id": "personal"}, json=_request(execution_id)
    )
    assert first.status_code == 200
    replay = client.post(
        "/api/v1/analysis", headers={"x-arena-project-id": "personal"}, json=_request(execution_id)
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True

    with service.repository.transaction() as conn:
        original = dict(conn.execute(select(analysis_reports)).mappings().one())
        conn.execute(insert(executions).values(
            id="execution-two", experiment_id="experiment-one", status="completed", parameters={}
        ))
        conn.execute(insert(analysis_reports).values(
            **(original | {"id": "b" * 64, "execution_id": "execution-two"})
        ))
    page_one = client.get(
        "/api/v1/analysis-reports?limit=1&offset=0", headers={"x-arena-project-id": "personal"}
    )
    assert page_one.status_code == 200
    assert page_one.json()["pagination"]["next_offset"] == 1
    page_two = client.get(
        "/api/v1/analysis-reports?limit=1&offset=1", headers={"x-arena-project-id": "personal"}
    )
    assert page_two.status_code == 200
    assert len(page_two.json()["analysis_reports"]) == 1
    filtered = client.get(
        "/api/v1/analysis-reports?execution_id=execution-two", headers={"x-arena-project-id": "personal"}
    )
    assert filtered.status_code == 200
    assert [item["execution_id"] for item in filtered.json()["analysis_reports"]] == ["execution-two"]
    assert client.get(
        "/api/v1/analysis-reports?limit=101", headers={"x-arena-project-id": "personal"}
    ).status_code == 400

    service.repository.create_project("Other", project_id="other")
    isolated = client.get(
        f"/api/v1/analysis-reports/{first.json()['report_digest']}",
        headers={"x-arena-project-id": "other"},
    )
    assert isolated.status_code == 404
    assert isolated.json()["error"]["code"] == "analysis_report_not_found"


def test_analysis_report_read_holds_on_tampered_artifact_or_binding(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    client = _client(service)
    created = client.post(
        "/api/v1/analysis", headers={"x-arena-project-id": "personal"}, json=_request(execution_id)
    ).json()
    digest = created["report_digest"]
    with service.repository.transaction() as conn:
        conn.execute(
            update(analysis_reports)
            .where(analysis_reports.c.report_digest == digest)
            .values(study_pack_hash="f" * 64)
        )
    mismatch = client.get(
        f"/api/v1/analysis-reports/{digest}", headers={"x-arena-project-id": "personal"}
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["verdict"] == "HOLD"
    assert mismatch.json()["error"]["code"] == "analysis_report_integrity_error"

    tampered_service, tampered_execution = _service(tmp_path / "tampered")
    tampered_client = _client(tampered_service)
    tampered = tampered_client.post(
        "/api/v1/analysis",
        headers={"x-arena-project-id": "personal"},
        json=_request(tampered_execution),
    ).json()
    Path(tampered_service.artifact_store.uri_for(tampered["artifact_digest"])).write_bytes(
        b"tampered"
    )
    artifact = tampered_client.get(
        f"/api/v1/analysis-reports/{tampered['report_digest']}",
        headers={"x-arena-project-id": "personal"},
    )
    assert artifact.status_code == 409
    assert artifact.json()["error"]["code"] == "analysis_report_integrity_error"


def test_analysis_report_get_never_builds_or_creates(tmp_path, monkeypatch) -> None:
    service, execution_id = _service(tmp_path)
    client = _client(service)
    created = client.post(
        "/api/v1/analysis", headers={"x-arena-project-id": "personal"}, json=_request(execution_id)
    ).json()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("GET must not build or create an analysis report")

    monkeypatch.setattr("services_v1.analysis.build_analysis_report", forbidden)
    monkeypatch.setattr(service.repository, "create_analysis_report", forbidden)
    response = client.get(
        f"/api/v1/analysis-reports/{created['report_digest']}",
        headers={"x-arena-project-id": "personal"},
    )
    assert response.status_code == 200
