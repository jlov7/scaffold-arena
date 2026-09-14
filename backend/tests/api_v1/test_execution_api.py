from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from api.v1.execution import router
from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import attempts, metadata
from services_v1 import ExecutionService, ProtocolRegistryService


def _pack() -> dict:
    def scenario(scenario_id: str, role: str = "candidate") -> dict:
        return {
            "scenario_id": scenario_id, "title": scenario_id, "task_family": "extract", "prompt": "Synthetic prompt.",
            "control_role": role, "deterministic_metrics": [{"metric_id": f"metric-{scenario_id}", "weight": 0.7, "oracle": "exact"}],
        }

    return {
        "study_pack_id": "pack-one", "version": "1.0.0", "title": "Synthetic Pack", "license_spdx": "MIT",
        "authors": [{"name": "Test"}], "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ["synthetic fixture exploration"], "limitations": ["No provider evidence."],
        "preregistration": {"reference_uri": "synthetic://pre", "content_hash": "a" * 64},
        "scenarios": [scenario("scenario-one"), scenario("positive-one", "positive"), scenario("negative-one", "negative"), scenario("anti-one", "anti_cheat")],
        "harnesses": [{"harness_id": "harness-one", "version": "1", "adapter": "recorded", "adapter_identity": "recorded-fixture", "adapter_digest": "2" * 64}],
        "experiments": [{"experiment_id": "template-one", "study_pack_id": "pack-one", "scenario_ids": ["scenario-one"], "harness_ids": ["harness-one"], "deterministic_weight": 0.7}],
    }


def _experiment() -> dict:
    return {
        "experiment_id": "experiment-one", "study_pack_id": "pack-one", "scenario_ids": ["scenario-one"], "harness_ids": ["harness-one"],
        "deterministic_weight": 0.7, "owner_approval": "approved", "sampling": {"max_tokens": 1},
        "budgets": {"max_attempts": 1, "max_cost_usd": 0, "max_latency_seconds": 1, "max_tokens": 1, "max_tool_calls": 0, "max_context_tokens": 1},
        "aggregate_budget": {"max_total_cost_usd": 0, "max_total_tokens": 1, "max_total_tool_calls": 0, "max_wall_time_seconds": 1, "max_attempts": 1},
    }


def _provenance() -> dict:
    return {
        "code_revision": "test", "code_hash": "b" * 64, "runtime_image": "test-image", "runtime_image_hash": "c" * 64,
        "environment_hash": "d" * 64, "prompt_hash": "e" * 64, "context_hash": "f" * 64, "tool_hash": "0" * 64,
        "source_refs": [{"source_uri": "synthetic://source", "content_hash": "1" * 64}], "captured_at": "2026-08-14T00:00:00Z",
    }


class LookupOnlyRegistry:
    def get(self, *_: object) -> object:
        return object()


def _client(tmp_path: Path) -> tuple[TestClient, ArenaRepository]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    registry = ProtocolRegistryService(repository, LocalArtifactStore(tmp_path / "artifacts"), personal_project_id="personal")
    registry.import_pack(json.dumps(_pack()).encode(), "application/json", project_id="personal")
    registry.create_experiment(_experiment(), project_id="personal")
    registry.freeze("experiment-one", project_id="personal")
    app = FastAPI()
    app.state.execution_api_service = ExecutionService(repository, registry.artifact_store, personal_project_id="personal", adapter_registry=LookupOnlyRegistry())
    app.include_router(router)
    return TestClient(app), repository


def test_execution_routes_are_control_only_with_sse_cursor_resume_and_ownership(tmp_path: Path) -> None:
    client, repository = _client(tmp_path)
    assert client.post("/api/v1/experiments/experiment-one/executions", json=_provenance()).status_code == 400
    first = client.post("/api/v1/experiments/experiment-one/executions", json=_provenance(), headers={"Idempotency-Key": "one"})
    assert first.status_code == 200
    replay = client.post("/api/v1/experiments/experiment-one/executions", json=_provenance(), headers={"Idempotency-Key": "one"})
    assert replay.json()["idempotent_replay"] is True
    execution_id = first.json()["execution_id"]
    with repository.engine.connect() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
    repository.append_attempt_event(attempt_id, "queued", {"access_token": "redact", "input_tokens": 3})
    assert client.post(f"/api/v1/executions/{execution_id}/cancel").status_code == 200
    stream = client.get(f"/api/v1/executions/{execution_id}/events")
    assert stream.status_code == 200
    assert "event: queued" in stream.text and '"input_tokens":3' in stream.text and "redact" not in stream.text
    cursor = next(line.removeprefix("id: ") for line in stream.text.splitlines() if line.startswith("id: "))
    assert "event: queued" not in client.get(f"/api/v1/executions/{execution_id}/events", headers={"Last-Event-ID": cursor}).text
    with repository.transaction() as conn:
        conn.execute(update(attempts).where(attempts.c.id == attempt_id).values(status="incomplete", result_metadata={"reason": "partial_trace"}))
    assert client.get(f"/api/v1/attempts/{attempt_id}").json()["status"] == "incomplete"
    repository.create_project("Other", project_id="other")
    assert client.get(f"/api/v1/attempts/{attempt_id}", headers={"x-arena-project-id": "other"}).status_code == 404
    assert client.post(f"/api/v1/executions/{execution_id}/resume").status_code == 409
    assert set(client.app.openapi()["paths"]["/api/v1/executions/{execution_id}/events"]) == {"get"}


def test_browser_recovery_execution_get_routes_are_read_only_paginated_and_redacted(tmp_path: Path, monkeypatch) -> None:
    client, repository = _client(tmp_path)
    created = client.post("/api/v1/experiments/experiment-one/executions", json=_provenance(), headers={"Idempotency-Key": "recovery"})
    assert created.status_code == 200
    execution_id = created.json()["execution_id"]
    with repository.engine.connect() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
    repository.append_attempt_event(attempt_id, "queued", {"api_key": "must-not-leak"})
    service = client.app.state.execution_api_service
    monkeypatch.setattr(service, "create_execution", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("GET must not create executions")))
    listing = client.get("/api/v1/executions?experiment_id=experiment-one&limit=1&offset=0")
    assert listing.status_code == 200
    assert listing.json()["pagination"]["limit"] == 1
    detail = client.get(f"/api/v1/executions/{execution_id}")
    assert detail.status_code == 200
    assert detail.json()["counts"]["attempts"] == 1
    assert "payload" not in str(detail.json()) and "must-not-leak" not in detail.text
    assert client.get("/api/v1/executions?limit=101").json()["error"]["code"] == "invalid_limit"
    repository.create_project("Other", project_id="other")
    assert client.get(f"/api/v1/executions/{execution_id}", headers={"x-arena-project-id": "other"}).status_code == 404
    assert set(client.app.openapi()["paths"]["/api/v1/executions"]) == {"get"}
