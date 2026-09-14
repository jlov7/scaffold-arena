from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

from adapters_v1 import AttemptInput, ProviderUsage
from execution_v1 import BudgetReservationService, InvocationRepository
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.invocation_schema import budget_reservations
from persistence_v1.jobs import JobLeaseRepository
from persistence_v1.schema import experiments, usage_ledger
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


def _start_invocation(repository: ArenaRepository, *, dispatch: bool) -> str:
    lease = JobLeaseRepository(repository).claim(
        "worker-one",
        lease_seconds=5,
        now=NOW,
        kind="attempt",
    )
    assert lease is not None
    invocations = InvocationRepository(repository)
    invocation = invocations.begin(lease, _input(), now=NOW)
    if dispatch:
        invocations.mark_dispatch_started(invocation, now=NOW)
    return invocation.invocation_id


def _usage() -> ProviderUsage:
    return ProviderUsage(
        evidence_source="provider_reported",
        input_tokens=2,
        output_tokens=3,
        total_tokens=5,
        context_tokens=2,
        tool_calls=0,
        provider_usage_digest=HASH_A,
        observed_provider_version="provider-v1",
        observed_endpoint_digest=HASH_A,
    )


def test_reservation_is_bound_to_current_invocation_and_commits_atomically(
    repository: ArenaRepository,
) -> None:
    invocation_id = _start_invocation(repository, dispatch=True)
    service = BudgetReservationService(repository)
    ledger_id = service.reserve_with_aggregate(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        max_attempts=2,
        max_total_cost_usd=2.0,
        max_tokens=256,
        max_tool_calls=2,
        max_total_tokens=512,
        max_total_tool_calls=4,
        now=NOW,
    )

    reserved = service.lifecycle(ledger_id)
    assert reserved.state == "reserved"
    assert reserved.invocation_id == invocation_id

    committed = service.reconcile(
        ledger_id,
        input_tokens=2,
        output_tokens=3,
        actual_cost_usd=0.01,
        provider_usage_digest=HASH_A,
        price_catalog_revision="catalog-v1",
        expected_cost_usd=0.01,
        usage=_usage(),
        now=NOW + timedelta(seconds=1),
    )
    assert committed.status == "reconciled"
    assert service.lifecycle(ledger_id).state == "committed"

    with pytest.raises(ValueError, match="terminal reservation"):
        service.release(ledger_id, reason="late cleanup")


def test_unknown_usage_and_mismatch_have_distinct_terminal_states(
    repository: ArenaRepository,
) -> None:
    _start_invocation(repository, dispatch=True)
    service = BudgetReservationService(repository)
    unknown_id = service.reserve(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        now=NOW,
    )
    service.unknown(unknown_id, usage=None, now=NOW + timedelta(seconds=1))
    assert service.lifecycle(unknown_id).state == "unknown_usage"

    mismatch_id = service.reserve(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        ledger_id="mismatch-ledger",
        now=NOW + timedelta(seconds=2),
    )
    service.mismatch(mismatch_id, usage=_usage(), now=NOW + timedelta(seconds=3))
    assert service.lifecycle(mismatch_id).state == "disputed"


def test_stranded_reservation_without_dispatch_expires_not_unknown(
    repository: ArenaRepository,
) -> None:
    _start_invocation(repository, dispatch=False)
    service = BudgetReservationService(repository)
    ledger_id = service.reserve(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        now=NOW,
    )

    reconciled = service.reconcile_stranded(
        now=NOW + timedelta(seconds=10),
        stale_after_seconds=5,
    )

    assert ledger_id in reconciled
    assert service.lifecycle(ledger_id).state == "expired"
    with repository.engine.connect() as connection:
        status = connection.execute(
            select(usage_ledger.c.cost_status).where(usage_ledger.c.id == ledger_id)
        ).scalar_one()
    assert status == "expired"


def test_stranded_reservation_after_possible_dispatch_becomes_unknown_usage(
    repository: ArenaRepository,
) -> None:
    _start_invocation(repository, dispatch=True)
    service = BudgetReservationService(repository)
    ledger_id = service.reserve(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        now=NOW,
    )

    reconciled = service.reconcile_stranded(
        now=NOW + timedelta(seconds=10),
        stale_after_seconds=5,
    )

    assert ledger_id in reconciled
    assert service.lifecycle(ledger_id).state == "unknown_usage"
    with repository.engine.connect() as connection:
        row = connection.execute(
            select(
                budget_reservations.c.state,
                usage_ledger.c.cost_status,
            )
            .select_from(
                budget_reservations.join(
                    usage_ledger,
                    budget_reservations.c.ledger_id == usage_ledger.c.id,
                )
            )
            .where(budget_reservations.c.ledger_id == ledger_id)
        ).one()
    assert row.state == "unknown_usage"
    assert row.cost_status == "unknown"


def test_release_proves_no_provider_dispatch_and_clears_reserved_status(
    repository: ArenaRepository,
) -> None:
    _start_invocation(repository, dispatch=False)
    service = BudgetReservationService(repository)
    ledger_id = service.reserve(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        now=NOW,
    )

    service.release(ledger_id, reason="pre-dispatch cancellation", now=NOW)

    assert service.lifecycle(ledger_id).state == "released"
    with repository.engine.connect() as connection:
        status = connection.execute(
            select(usage_ledger.c.cost_status).where(usage_ledger.c.id == ledger_id)
        ).scalar_one()
    assert status == "released"


def test_released_reservation_cannot_later_dispatch_a_provider(
    repository: ArenaRepository,
) -> None:
    invocation_id = _start_invocation(repository, dispatch=False)
    service = BudgetReservationService(repository)
    ledger_id = service.reserve(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        now=NOW,
    )
    service.release(ledger_id, reason="pre-dispatch cancellation", now=NOW)

    invocation = InvocationRepository(repository).get(invocation_id)
    with pytest.raises(ValueError, match="reservation was settled"):
        InvocationRepository(repository).mark_dispatch_started(invocation, now=NOW)


def test_unknown_usage_reservation_cannot_later_dispatch_a_provider(
    repository: ArenaRepository,
) -> None:
    invocation_id = _start_invocation(repository, dispatch=False)
    service = BudgetReservationService(repository)
    ledger_id = service.reserve(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        now=NOW,
    )
    service.unknown(ledger_id, now=NOW)

    invocation = InvocationRepository(repository).get(invocation_id)
    with pytest.raises(ValueError, match="reservation was settled"):
        InvocationRepository(repository).mark_dispatch_started(invocation, now=NOW)


def test_expiry_after_possible_dispatch_preserves_unknown_usage(
    repository: ArenaRepository,
) -> None:
    _start_invocation(repository, dispatch=True)
    service = BudgetReservationService(repository)
    ledger_id = service.reserve(
        "execution-one",
        "attempt-one",
        model_id="model-one",
        max_cost_usd=1.0,
        now=NOW,
    )

    lifecycle = service.expire(ledger_id, reason="lease elapsed", now=NOW)

    assert lifecycle.state == "unknown_usage"
    with repository.engine.connect() as connection:
        status = connection.execute(
            select(usage_ledger.c.cost_status).where(usage_ledger.c.id == ledger_id)
        ).scalar_one()
    assert status == "unknown"
