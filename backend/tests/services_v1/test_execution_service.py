from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import attempts, jobs, metadata
from services_v1 import ExecutionError, ExecutionService, ProtocolRegistryService


def pack_payload() -> dict:
    return {
        "study_pack_id": "pack-one", "version": "1.0.0", "title": "Synthetic Pack", "license_spdx": "MIT",
        "authors": [{"name": "Test"}], "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ["synthetic fixture exploration"], "limitations": ["No provider evidence."],
        "preregistration": {"reference_uri": "synthetic://pre", "content_hash": "a" * 64},
        "scenarios": [
            {"scenario_id": "scenario-one", "title": "Scenario", "task_family": "extract", "prompt": "Synthetic prompt.", "deterministic_metrics": [{"metric_id": "metric-one", "weight": 0.7, "oracle": "exact"}]},
            {"scenario_id": "positive-one", "title": "Positive", "task_family": "extract", "prompt": "Synthetic prompt.", "control_role": "positive", "deterministic_metrics": [{"metric_id": "metric-two", "weight": 0.7, "oracle": "exact"}]},
            {"scenario_id": "negative-one", "title": "Negative", "task_family": "extract", "prompt": "Synthetic prompt.", "control_role": "negative", "deterministic_metrics": [{"metric_id": "metric-three", "weight": 0.7, "oracle": "exact"}]},
            {"scenario_id": "anti-one", "title": "Anti", "task_family": "extract", "prompt": "Synthetic prompt.", "control_role": "anti_cheat", "deterministic_metrics": [{"metric_id": "metric-four", "weight": 0.7, "oracle": "exact"}]},
        ],
        "harnesses": [{
            "harness_id": "harness-one", "version": "1", "adapter": "recorded", "adapter_identity": "recorded-fixture",
            "adapter_digest": "2" * 64,
        }],
        "experiments": [{"experiment_id": "template-one", "study_pack_id": "pack-one", "scenario_ids": ["scenario-one"], "harness_ids": ["harness-one"], "deterministic_weight": 0.7}],
    }


def experiment_payload(*, experiment_id: str = "experiment-one") -> dict:
    return {
        "experiment_id": experiment_id, "study_pack_id": "pack-one", "scenario_ids": ["scenario-one"],
        "harness_ids": ["harness-one"], "deterministic_weight": 0.7, "owner_approval": "approved",
        "sampling": {"max_tokens": 1},
        "budgets": {"max_attempts": 1, "max_cost_usd": 0, "max_latency_seconds": 1, "max_tokens": 1, "max_tool_calls": 0, "max_context_tokens": 1},
        "aggregate_budget": {"max_total_cost_usd": 0, "max_total_tokens": 1, "max_total_tool_calls": 0, "max_wall_time_seconds": 1, "max_attempts": 1},
    }


def provenance() -> dict:
    return {
        "code_revision": "test", "code_hash": "b" * 64, "runtime_image": "test-image", "runtime_image_hash": "c" * 64,
        "environment_hash": "d" * 64, "prompt_hash": "e" * 64, "context_hash": "f" * 64, "tool_hash": "0" * 64,
        "source_refs": [{"source_uri": "synthetic://source", "content_hash": "1" * 64}], "captured_at": "2026-08-14T00:00:00Z",
    }


class ForbiddenAdapterRegistry:
    def get(self, *_: object) -> object:
        return object()


@pytest.fixture
def service(tmp_path: Path) -> ExecutionService:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    registry = ProtocolRegistryService(repository, LocalArtifactStore(tmp_path / "artifacts"), personal_project_id="personal")
    registry.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    registry.create_experiment(experiment_payload(), project_id="personal")
    registry.freeze("experiment-one", project_id="personal")
    return ExecutionService(repository, registry.artifact_store, personal_project_id="personal", adapter_registry=ForbiddenAdapterRegistry())


def test_create_is_durable_only_idempotent_and_conflict_safe(service: ExecutionService) -> None:
    created = service.create_execution("experiment-one", provenance(), project_id=None, request_key="same-request")
    replay = service.create_execution("experiment-one", provenance(), project_id=None, request_key="same-request")
    assert created["expected_attempts"] == 1
    assert created["provider_execution_started_by_request"] is False
    assert replay["execution_id"] == created["execution_id"]
    assert replay["idempotent_replay"] is True
    changed = provenance() | {"code_revision": "changed"}
    with pytest.raises(ExecutionError) as error:
        service.create_execution("experiment-one", changed, project_id=None, request_key="same-request")
    assert error.value.status_code == 409


def test_events_cancel_and_project_ownership(service: ExecutionService) -> None:
    created = service.create_execution("experiment-one", provenance(), project_id=None, request_key="events")
    with service.repository.engine.connect() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
    service.repository.append_attempt_event(attempt_id, "queued", {"api_key": "must-not-leak"})
    events, terminal = service.events(created["execution_id"], project_id="personal", cursor=None)
    assert terminal is None
    assert len(events) == 1
    assert events[0].payload["api_key"] == "[REDACTED]"
    assert service._redact({"input_tokens": 3, "access_token": "must-not-leak"}) == {
        "input_tokens": 3, "access_token": "[REDACTED]",
    }
    replay, _ = service.events(created["execution_id"], project_id="personal", cursor=events[0].cursor)
    assert replay == []
    cancelled = service.cancel(created["execution_id"], project_id="personal")
    assert cancelled["cancellation_requested_jobs"] == 1
    assert service.cancel(created["execution_id"], project_id="personal")["cancellation_requested_jobs"] == 0
    service.repository.create_project("Other", project_id="other")
    with pytest.raises(ExecutionError) as error:
        service.attempt(attempt_id, project_id="other")
    assert error.value.status_code == 404


def test_browser_recovery_execution_reads_are_paginated_redacted_and_project_scoped(service: ExecutionService) -> None:
    first = service.create_execution("experiment-one", provenance(), project_id="personal", request_key="recovery-one")
    second = service.create_execution("experiment-one", provenance(), project_id="personal", request_key="recovery-two")
    with service.repository.engine.connect() as conn:
        job_id = conn.execute(select(jobs.c.id).where(jobs.c.execution_id == first["execution_id"])).scalar_one()
    with service.repository.transaction() as conn:
        conn.execute(jobs.update().where(jobs.c.id == job_id).values(payload={"api_key": "must-not-leak"}))

    page = service.list_executions(project_id="personal", experiment_id="experiment-one", limit=1, offset=0)
    assert len(page["executions"]) == 1
    assert page["pagination"]["next_offset"] == 1
    assert "parameters" not in page["executions"][0]
    detail = service.execution(first["execution_id"], project_id="personal")
    assert detail["counts"] == {"attempts": 1, "jobs": 1}
    assert detail["jobs"][0]["job_id"] == job_id
    assert "payload" not in detail["jobs"][0]
    assert "must-not-leak" not in str(detail)
    service.repository.create_project("Other", project_id="other")
    assert service.list_executions(project_id="other")["executions"] == []
    with pytest.raises(ExecutionError) as denied:
        service.execution(second["execution_id"], project_id="other")
    assert denied.value.status_code == 404
    with pytest.raises(ExecutionError) as missing:
        service.execution("missing", project_id="personal")
    assert missing.value.status_code == 404
    with pytest.raises(ExecutionError) as invalid:
        service.list_executions(project_id="personal", limit=101)
    assert invalid.value.code == "invalid_limit"


def test_events_do_not_split_event_read_from_terminal_state(service: ExecutionService, monkeypatch: pytest.MonkeyPatch) -> None:
    created = service.create_execution("experiment-one", provenance(), project_id=None, request_key="stream-snapshot")
    with service.repository.engine.connect() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
    service.repository.append_attempt_event(attempt_id, "queued")
    legacy_read = service.repository.list_execution_events_after

    def stale_read(execution_id: str, cursor: int):
        events = legacy_read(execution_id, cursor)
        with service.repository.transaction() as conn:
            from persistence_v1.schema import executions

            conn.execute(executions.update().where(executions.c.id == execution_id).values(status="completed"))
        return events

    monkeypatch.setattr(service.repository, "list_execution_events_after", stale_read)
    events, terminal = service.events(created["execution_id"], project_id="personal", cursor=None)
    assert len(events) == 1
    assert terminal is None
