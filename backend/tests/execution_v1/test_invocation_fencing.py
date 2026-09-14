from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update

from adapters_v1 import AttemptInput, InvocationContext
from execution_v1 import DuplicateProviderRequest, InvocationRepository
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.jobs import (
    LEASE_RECLAIM_BACKOFF_BASE_SECONDS,
    LEASE_RECLAIM_GRACE_SECONDS,
    JobLease,
    JobLeaseRepository,
)
from persistence_v1.schema import experiments
from protocol_v1 import AttemptEnvelope, BudgetSpec, ExecutionProvenance, ScenarioSpec

HASH_A = "a" * 64
NOW = datetime.now(UTC)


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
    execution_id = repository.create_execution("experiment-one", execution_id="execution-one")
    episode_id = repository.create_episode(
        execution_id,
        0,
        episode_id="episode-one",
        scenario_id="scenario-one",
    )
    repository.create_attempt(episode_id, 0, attempt_id="attempt-one")
    JobLeaseRepository(repository).enqueue(
        execution_id,
        attempt_id="attempt-one",
        job_id="job-one",
        payload={"attempt_input": _input().model_dump(mode="json")},
        available_at=NOW,
    )
    return repository


def _input() -> AttemptInput:
    scenario = ScenarioSpec(
        scenario_id="scenario-one",
        title="Synthetic scenario",
        task_family="fixture",
        prompt="Synthetic fixture prompt.",
    )
    attempt = AttemptEnvelope(
        attempt_id="attempt-one",
        episode_id="episode-one",
        ordinal=1,
        provider_model="model-one",
        provider="provider-one",
        endpoint_id="endpoint-one",
        pinned_endpoint_digest=HASH_A,
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


def _claim(
    repository: ArenaRepository,
    owner: str,
    now: datetime,
) -> JobLease:
    lease = JobLeaseRepository(repository).claim(
        owner,
        lease_seconds=5,
        now=now,
        kind="attempt",
    )
    assert lease is not None
    return lease


def test_invocation_context_is_content_addressed_and_secret_free() -> None:
    first = InvocationContext.bind(
        invocation_id="invocation-one",
        attempt_id="attempt-one",
        generation=1,
        fence_token=HASH_A,
        provider_idempotency_key="arena-idempotency-key",
        aggregate_deadline_at=NOW + timedelta(seconds=60),
    )
    second = first.model_copy(update={"generation": 2})

    assert first.context_digest != second.context_digest
    assert "authorization" not in first.model_dump_json().lower()
    assert "api_key" not in first.model_dump_json().lower()


def test_new_generation_marks_possible_prior_invocation_stale_and_ambiguous(
    repository: ArenaRepository,
) -> None:
    invocations = InvocationRepository(repository)
    first_lease = _claim(repository, "worker-one", NOW)
    first = invocations.begin(first_lease, _input(), now=NOW)
    invocations.mark_dispatch_started(first, now=NOW)

    reclaim_at = NOW + timedelta(seconds=5 + LEASE_RECLAIM_GRACE_SECONDS)
    assert JobLeaseRepository(repository).reclaim_expired(now=reclaim_at) == 1
    second_time = reclaim_at + timedelta(seconds=LEASE_RECLAIM_BACKOFF_BASE_SECONDS)
    second_lease = _claim(repository, "worker-two", second_time)
    second = invocations.begin(second_lease, _input(), now=second_time)

    previous = invocations.get(first.invocation_id)
    current = invocations.get(second.invocation_id)
    assert previous.admission_state == "stale"
    assert previous.side_effect_state == "ambiguous"
    assert current.admission_state == "current"
    assert current.generation == 2
    assert current.fence_token != previous.fence_token
    assert current.provider_idempotency_key == previous.provider_idempotency_key

    assert not invocations.admit_terminal(
        previous,
        result_digest="b" * 64,
        terminal_outcome="completed",
        usage_state="unknown",
        now=second_time,
    )
    assert invocations.admit_terminal(
        current,
        result_digest="c" * 64,
        terminal_outcome="completed",
        usage_state="reconciled",
        now=second_time,
    )


def test_duplicate_provider_request_id_is_explicitly_ambiguous(
    repository: ArenaRepository,
) -> None:
    invocations = InvocationRepository(repository)
    first = invocations.begin(_claim(repository, "worker-one", NOW), _input(), now=NOW)
    invocations.mark_dispatch_started(first, now=NOW)
    invocations.observe_provider_request(first, "provider-request-one", now=NOW)

    reclaim_at = NOW + timedelta(seconds=5 + LEASE_RECLAIM_GRACE_SECONDS)
    assert JobLeaseRepository(repository).reclaim_expired(now=reclaim_at) == 1
    second_time = reclaim_at + timedelta(seconds=LEASE_RECLAIM_BACKOFF_BASE_SECONDS)
    second = invocations.begin(
        _claim(repository, "worker-two", second_time),
        _input(),
        now=second_time,
    )
    invocations.mark_dispatch_started(second, now=second_time)

    with pytest.raises(DuplicateProviderRequest, match="provider request"):
        invocations.observe_provider_request(
            second,
            "provider-request-one",
            now=second_time,
        )

    previous = invocations.get(first.invocation_id)
    duplicate = invocations.get(second.invocation_id)
    assert previous.side_effect_state == "ambiguous"
    assert duplicate.side_effect_state == "ambiguous"
    assert duplicate.admission_state == "duplicate"


def test_cancel_acknowledgement_states_are_monotonic(
    repository: ArenaRepository,
) -> None:
    invocations = InvocationRepository(repository)
    invocation = invocations.begin(
        _claim(repository, "worker-one", NOW),
        _input(),
        now=NOW,
    )

    invocations.request_cancel(invocation)
    invocations.mark_cancel_dispatched(invocation)
    invocations.mark_cancel_acknowledged(invocation)

    recorded = invocations.get(invocation.invocation_id)
    assert recorded.cancellation_state == "acknowledged"
    with pytest.raises(ValueError, match="cannot move backwards"):
        invocations.request_cancel(recorded)


def test_one_external_result_is_admitted_only_once(
    repository: ArenaRepository,
) -> None:
    invocations = InvocationRepository(repository)
    invocation = invocations.begin(
        _claim(repository, "worker-one", NOW),
        _input(),
        now=NOW,
    )
    invocations.mark_dispatch_started(invocation, now=NOW)

    assert invocations.admit_terminal(
        invocation,
        result_digest="b" * 64,
        terminal_outcome="completed",
        usage_state="unknown",
        now=NOW,
    )
    assert not invocations.admit_terminal(
        invocation,
        result_digest="c" * 64,
        terminal_outcome="failed",
        usage_state="unknown",
        now=NOW,
    )

    recorded = invocations.get(invocation.invocation_id)
    assert recorded.provider_result_digest == "b" * 64
    assert recorded.terminal_outcome == "completed"


def test_provider_request_identity_cannot_rewrite_a_terminal_admission(
    repository: ArenaRepository,
) -> None:
    invocations = InvocationRepository(repository)
    invocation = invocations.begin(
        _claim(repository, "worker-one", NOW),
        _input(),
        now=NOW,
    )
    invocations.mark_dispatch_started(invocation, now=NOW)
    assert invocations.admit_terminal(
        invocation,
        result_digest="b" * 64,
        terminal_outcome="completed",
        usage_state="unknown",
        now=NOW,
    )

    with pytest.raises(ValueError, match="before terminal result"):
        invocations.observe_provider_request(
            invocation,
            "late-provider-request",
            now=NOW,
        )
