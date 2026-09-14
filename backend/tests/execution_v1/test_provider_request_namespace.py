from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update

from adapters_v1 import AttemptInput
from execution_v1 import DuplicateProviderRequest, InvocationRepository
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.invocation_schema import invocation_records
from persistence_v1.jobs import (
    LEASE_RECLAIM_BACKOFF_BASE_SECONDS,
    LEASE_RECLAIM_BACKOFF_CAP_SECONDS,
    LEASE_RECLAIM_GRACE_SECONDS,
    MAX_LEASE_GENERATIONS,
    JobLease,
    JobLeaseRepository,
)
from persistence_v1.schema import experiments
from protocol_v1 import AttemptEnvelope, BudgetSpec, ExecutionProvenance, ScenarioSpec

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime(2026, 8, 17, tzinfo=UTC)


def _input(
    *,
    attempt_id: str,
    episode_id: str,
    endpoint_digest: str,
    model: str = "model-one",
) -> AttemptInput:
    scenario = ScenarioSpec(
        scenario_id=f"scenario-{attempt_id}",
        title="Synthetic scenario",
        task_family="fixture",
        prompt="Synthetic fixture prompt.",
    )
    attempt = AttemptEnvelope(
        attempt_id=attempt_id,
        episode_id=episode_id,
        ordinal=1,
        provider_model=model,
        provider="provider-one",
        endpoint_id=f"endpoint-{endpoint_digest[:8]}",
        pinned_endpoint_digest=endpoint_digest,
        harness_id="harness-one",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=2,
            max_cost_usd=1.0,
            max_latency_seconds=30.0,
            max_tokens=256,
            max_tool_calls=2,
            max_context_tokens=2048,
        ),
        provenance=ExecutionProvenance(
            code_revision="abc123",
            code_hash=HASH_A,
            runtime_image="runtime@sha256:abc",
            runtime_image_hash=HASH_A,
            environment_hash=HASH_A,
            prompt_hash=HASH_A,
            context_hash=HASH_A,
            tool_hash=HASH_A,
            source_refs=(
                {"source_uri": "synthetic://source", "content_hash": HASH_A},
            ),
            captured_at=NOW,
        ),
        request_hash=HASH_A,
        status="queued",
        queued_at=NOW,
    )
    return AttemptInput.bind(scenario, attempt)


@pytest.fixture
def repository(tmp_path: Path) -> ArenaRepository:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Test", project_id="project-one")
    repository.register_artifact(HASH_A, size_bytes=1, storage_uri="local://pack")
    pack_id = repository.create_study_pack_version(
        "project-one",
        "pack",
        "1.0.0",
        HASH_A,
        study_pack_id="pack-one",
    )
    repository.create_experiment(
        "project-one",
        pack_id,
        "experiment",
        experiment_id="experiment-one",
        definition={},
    )
    with repository.transaction() as connection:
        connection.execute(
            update(experiments)
            .where(experiments.c.id == "experiment-one")
            .values(
                owner_approval="approved",
                frozen_at=NOW,
                spec_hash=HASH_A,
                study_pack_hash=HASH_A,
            )
        )
    execution_id = repository.create_execution(
        "experiment-one", execution_id="execution-one"
    )
    _enqueue_attempt(
        repository,
        execution_id=execution_id,
        ordinal=0,
        attempt_id="attempt-one",
        endpoint_digest=HASH_A,
        model="model-one",
    )
    return repository


def _enqueue_attempt(
    repository: ArenaRepository,
    *,
    execution_id: str,
    ordinal: int,
    attempt_id: str,
    endpoint_digest: str,
    model: str,
) -> AttemptInput:
    episode_id = f"episode-{attempt_id.removeprefix('attempt-')}"
    repository.create_episode(
        execution_id,
        ordinal,
        episode_id=episode_id,
        scenario_id=f"scenario-{attempt_id}",
    )
    repository.create_attempt(episode_id, 0, attempt_id=attempt_id)
    bound = _input(
        attempt_id=attempt_id,
        episode_id=episode_id,
        endpoint_digest=endpoint_digest,
        model=model,
    )
    JobLeaseRepository(repository).enqueue(
        execution_id,
        attempt_id=attempt_id,
        job_id=f"job-{attempt_id.removeprefix('attempt-')}",
        payload={"attempt_input": bound.model_dump(mode="json")},
        available_at=NOW,
    )
    return bound


def _claim(repository: ArenaRepository, owner: str) -> JobLease:
    lease = JobLeaseRepository(repository).claim(
        owner,
        lease_seconds=30,
        now=NOW,
        kind="attempt",
    )
    assert lease is not None
    return lease


def test_invocation_schema_persists_provider_request_namespace() -> None:
    assert "provider_request_namespace" in invocation_records.c


def test_namespace_is_stable_across_lease_generations(
    repository: ArenaRepository,
) -> None:
    invocations = InvocationRepository(repository)
    first_input = _input(
        attempt_id="attempt-one",
        episode_id="episode-one",
        endpoint_digest=HASH_A,
    )
    leases = JobLeaseRepository(repository)
    lease = _claim(repository, "worker-one")
    records = [invocations.begin(lease, first_input, now=NOW)]
    claimed_at = NOW

    # Every permitted reclaim generation binds the same immutable provider
    # request identity; the terminal cap has no successor generation.
    for generation in range(1, MAX_LEASE_GENERATIONS):
        reclaim_at = claimed_at + timedelta(seconds=30 + LEASE_RECLAIM_GRACE_SECONDS)
        assert leases.reclaim_expired(now=reclaim_at) == 1
        backoff = min(
            LEASE_RECLAIM_BACKOFF_BASE_SECONDS * (2 ** (generation - 1)),
            LEASE_RECLAIM_BACKOFF_CAP_SECONDS,
        )
        claimed_at = reclaim_at + timedelta(seconds=backoff)
        lease = leases.claim(
            f"worker-{generation + 1}",
            lease_seconds=30,
            now=claimed_at,
            kind="attempt",
        )
        assert lease is not None
        records.append(invocations.begin(lease, first_input, now=claimed_at))

    assert {record.provider_request_namespace for record in records} == {records[0].provider_request_namespace}
    assert {record.provider_idempotency_key for record in records} == {records[0].provider_idempotency_key}


def test_same_request_id_on_different_pinned_endpoints_is_not_a_duplicate(
    repository: ArenaRepository,
) -> None:
    second_input = _enqueue_attempt(
        repository,
        execution_id="execution-one",
        ordinal=1,
        attempt_id="attempt-two",
        endpoint_digest=HASH_B,
        model="model-one",
    )
    first_input = _input(
        attempt_id="attempt-one",
        episode_id="episode-one",
        endpoint_digest=HASH_A,
    )
    invocations = InvocationRepository(repository)
    first = invocations.begin(_claim(repository, "worker-one"), first_input, now=NOW)
    invocations.mark_dispatch_started(first, now=NOW)
    invocations.observe_provider_request(first, "request-one", now=NOW)

    second = invocations.begin(_claim(repository, "worker-two"), second_input, now=NOW)
    invocations.mark_dispatch_started(second, now=NOW)
    observed = invocations.observe_provider_request(second, "request-one", now=NOW)

    assert first.provider_request_namespace != observed.provider_request_namespace
    assert observed.admission_state == "current"
    assert observed.side_effect_state == "observed"


def test_model_change_on_same_endpoint_does_not_evade_duplicate_detection(
    repository: ArenaRepository,
) -> None:
    second_input = _enqueue_attempt(
        repository,
        execution_id="execution-one",
        ordinal=1,
        attempt_id="attempt-two",
        endpoint_digest=HASH_A,
        model="model-two",
    )
    first_input = _input(
        attempt_id="attempt-one",
        episode_id="episode-one",
        endpoint_digest=HASH_A,
        model="model-one",
    )
    invocations = InvocationRepository(repository)
    first = invocations.begin(_claim(repository, "worker-one"), first_input, now=NOW)
    invocations.mark_dispatch_started(first, now=NOW)
    invocations.observe_provider_request(first, "request-one", now=NOW)

    second = invocations.begin(_claim(repository, "worker-two"), second_input, now=NOW)
    invocations.mark_dispatch_started(second, now=NOW)
    with pytest.raises(DuplicateProviderRequest, match="provider request"):
        invocations.observe_provider_request(second, "request-one", now=NOW)

    assert first.provider_request_namespace == second.provider_request_namespace
    assert invocations.get(second.invocation_id).admission_state == "duplicate"


def test_same_external_result_digest_across_invocations_is_not_admitted_twice(
    repository: ArenaRepository,
) -> None:
    second_input = _enqueue_attempt(
        repository,
        execution_id="execution-one",
        ordinal=1,
        attempt_id="attempt-two",
        endpoint_digest=HASH_A,
        model="model-one",
    )
    first_input = _input(
        attempt_id="attempt-one",
        episode_id="episode-one",
        endpoint_digest=HASH_A,
    )
    invocations = InvocationRepository(repository)
    first = invocations.begin(_claim(repository, "worker-one"), first_input, now=NOW)
    second = invocations.begin(
        _claim(repository, "worker-two"), second_input, now=NOW
    )
    invocations.mark_dispatch_started(first, now=NOW)
    invocations.mark_dispatch_started(second, now=NOW)

    assert invocations.admit_terminal(
        first,
        result_digest="d" * 64,
        terminal_outcome="completed",
        usage_state="reconciled",
        now=NOW,
    )
    assert not invocations.admit_terminal(
        second,
        result_digest="d" * 64,
        terminal_outcome="completed",
        usage_state="reconciled",
        now=NOW,
    )

    admitted = invocations.get(first.invocation_id)
    duplicate = invocations.get(second.invocation_id)
    assert admitted.provider_result_digest == "d" * 64
    assert admitted.side_effect_state == "ambiguous"
    assert duplicate.provider_result_digest is None
    assert duplicate.terminal_outcome is None
    assert duplicate.admission_state == "duplicate"
    assert duplicate.side_effect_state == "ambiguous"
    assert duplicate.usage_state == "unknown"
