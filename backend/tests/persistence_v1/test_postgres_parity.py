from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Event

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import event, inspect, select
from sqlalchemy.exc import DBAPIError, IntegrityError

from adapters_v1 import AttemptInput
from execution_v1 import (
    DuplicateProviderRequest,
    ExperimentController,
    InvocationRecord,
    InvocationRepository,
)
from persistence_v1 import (
    ArenaRepository,
    FrozenExperimentError,
    ImmutableEvaluationConflict,
    ImmutableVersionConflict,
    create_persistence_engine,
    metadata,
)
from persistence_v1.jobs import (
    LEASE_RECLAIM_BACKOFF_BASE_SECONDS,
    LEASE_RECLAIM_GRACE_SECONDS,
    JobLeaseRepository,
)
from persistence_v1.schema import (
    artifacts,
    attempts,
    executions,
    experiments,
    jobs,
    projects,
    usage_ledger,
)
from protocol_v1 import (
    AttemptEnvelope,
    BudgetSpec,
    ExecutionProvenance,
    ExperimentSpec,
    HarnessSpec,
    ScenarioSpec,
)
from protocol_v1 import freeze_experiment as freeze_protocol_experiment
from protocol_v1.models import SamplingSpec

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def postgres_engine():
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL is required; run scripts/test-postgres-v1.sh")
    backend_root = Path(__file__).parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_persistence_engine(url, worker_concurrency=2)
    yield engine
    engine.dispose()


@pytest.fixture
def repository(postgres_engine) -> ArenaRepository:
    return ArenaRepository(postgres_engine)


def _frozen_attempt(repository: ArenaRepository) -> tuple[str, str, str, str]:
    project = repository.create_project("Postgres parity")
    digest = "a" * 64
    repository.register_artifact(digest, size_bytes=1, storage_uri="test://postgres-parity")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", digest)
    experiment = repository.create_experiment(project, pack, "experiment", owner_approval="approved", experiment_id=_experiment_id())
    definition, spec_hash = _frozen_definition(experiment, digest)
    repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash=digest)
    execution = repository.create_execution(experiment)
    episode = repository.create_episode(execution, 0)
    return project, repository.create_attempt(episode, 0), experiment, execution


def _invocation_input(
    *,
    attempt_id: str,
    episode_id: str,
    queued_at: datetime,
) -> AttemptInput:
    return AttemptInput.bind(
        ScenarioSpec(
            scenario_id=f"scenario-{attempt_id}",
            title="Postgres invocation race fixture",
            task_family="fixture",
            prompt="Synthetic invocation race fixture.",
        ),
        AttemptEnvelope(
            attempt_id=attempt_id,
            episode_id=episode_id,
            ordinal=1,
            provider_model="recorded",
            provider="postgres-race-provider",
            endpoint_id="postgres-race-endpoint",
            pinned_endpoint_digest="b" * 64,
            harness_id="harness-one",
            factor_assignments={},
            budget=BudgetSpec(
                max_attempts=2,
                max_cost_usd=1,
                max_latency_seconds=30,
                max_tokens=256,
                max_tool_calls=0,
                max_context_tokens=256,
            ),
            provenance=ExecutionProvenance(
                code_revision="postgres-race",
                code_hash="b" * 64,
                runtime_image="postgres-race",
                runtime_image_hash="b" * 64,
                environment_hash="b" * 64,
                prompt_hash="b" * 64,
                context_hash="b" * 64,
                tool_hash="b" * 64,
                source_refs=(
                    {
                        "source_uri": "fixture://postgres-race",
                        "content_hash": "b" * 64,
                    },
                ),
                captured_at=queued_at,
            ),
            request_hash="b" * 64,
            status="queued",
            queued_at=queued_at,
        ),
    )


def _live_invocation_pair(
    repository: ArenaRepository,
    project_id: str,
    execution_id: str,
) -> tuple[InvocationRepository, tuple[InvocationRecord, InvocationRecord], datetime]:
    queued_at = datetime.now(UTC)
    inputs: dict[str, AttemptInput] = {}
    leases = JobLeaseRepository(repository)
    for ordinal in (1, 2):
        episode_id = repository.create_episode(execution_id, ordinal)
        attempt_id = repository.create_attempt(episode_id, 0)
        bound = _invocation_input(
            attempt_id=attempt_id,
            episode_id=episode_id,
            queued_at=queued_at,
        )
        inputs[attempt_id] = bound
        leases.enqueue(
            execution_id,
            attempt_id=attempt_id,
            payload={"attempt_input": bound.model_dump(mode="json")},
        )
    observed_at = datetime.now(UTC)
    first_lease = leases.claim(
        "provider-race-worker-one",
        lease_seconds=30,
        now=observed_at,
        project_id=project_id,
    )
    second_lease = leases.claim(
        "provider-race-worker-two",
        lease_seconds=30,
        now=observed_at,
        project_id=project_id,
    )
    assert first_lease is not None and second_lease is not None
    invocations = InvocationRepository(repository)
    first = invocations.begin(
        first_lease,
        inputs[str(first_lease.attempt_id)],
        now=observed_at,
    )
    second = invocations.begin(
        second_lease,
        inputs[str(second_lease.attempt_id)],
        now=observed_at,
    )
    pair = (first, second)
    for invocation in pair:
        invocations.mark_dispatch_started(invocation, now=observed_at)
    return invocations, pair, observed_at


def _experiment_id() -> str:
    return f"experiment-{uuid.uuid4().hex}"


def _frozen_definition(experiment_id: str, study_pack_hash: str) -> tuple[dict[str, object], str]:
    frozen = freeze_protocol_experiment(
        ExperimentSpec(
            experiment_id=experiment_id,
            study_pack_id="pack-one",
            scenario_ids=("scenario-one",),
            harness_ids=("harness-one",),
            deterministic_weight=0.7,
            owner_approval="approved",
        ),
        study_pack_hash,
    )
    return frozen.model_dump(mode="json"), str(frozen.freeze_hash)


def test_postgres_alembic_schema_equals_metadata(postgres_engine) -> None:
    assert set(inspect(postgres_engine).get_table_names()) >= set(metadata.tables)
    with postgres_engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), metadata) == []


def test_postgres_repository_contract_guards_and_usage(repository: ArenaRepository) -> None:
    project, attempt, experiment, execution = _frozen_attempt(repository)
    assert repository.create_user(project, email="parity@example.test")
    assert repository.get_study_pack_version(project, "pack", "1.0.0")["content_digest"] == "a" * 64
    assert repository.append_attempt_event(attempt, "started", {"source": "postgres"}) == 1
    assert repository.list_attempt_events(attempt)[0]["payload"] == {"source": "postgres"}
    assert repository.record_legacy_import(project, "a" * 64, source_format="fixture", observed_fields=["status"])
    with pytest.raises(FrozenExperimentError):
        repository.update_experiment_definition(experiment, {})
    with pytest.raises(FrozenExperimentError):
        repository.set_experiment_owner_approval(experiment, "rejected")
    with pytest.raises(DBAPIError, match="frozen experiments are immutable"), repository.transaction() as connection:
        connection.execute(experiments.update().where(experiments.c.id == experiment).values(name="tampered"))
    with pytest.raises(RuntimeError), repository.transaction() as connection:
        connection.execute(projects.insert().values(id="rolled-back-" + attempt, name="Nope"))
        raise RuntimeError("abort")
    with repository.engine.connect() as connection:
        assert connection.execute(select(projects.c.id).where(projects.c.id == "rolled-back-" + attempt)).scalar_one_or_none() is None
    with repository.transaction() as connection:
        connection.execute(usage_ledger.insert().values(id="unknown-" + attempt, execution_id=execution, attempt_id=attempt, model_id="model", cost_status="unknown"))
    with pytest.raises(IntegrityError), repository.transaction() as connection:
        connection.execute(usage_ledger.insert().values(id="bad-" + attempt, execution_id=execution, attempt_id=attempt, model_id="model", cost_status="reconciled", cost_usd=1, actual_cost_usd=1))
    with repository.transaction() as connection:
        connection.execute(usage_ledger.insert().values(id="ok-" + attempt, execution_id=execution, attempt_id=attempt, model_id="model", input_tokens=1, output_tokens=2, total_tokens=3, context_tokens=1, tool_calls=0, cost_status="reconciled", cost_usd=1, actual_cost_usd=1, price_catalog_revision="parity", provider_usage_digest="d" * 64))


def test_postgres_concurrent_artifact_registration_replays_identical_content(
    repository: ArenaRepository,
) -> None:
    digest = (uuid.uuid4().hex + uuid.uuid4().hex)
    barrier = Barrier(2)

    def register() -> None:
        barrier.wait()
        repository.register_artifact(
            digest,
            size_bytes=7,
            storage_uri="test://postgres-race-artifact",
            media_type="application/test",
            content_metadata={"source": "postgres-race"},
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(lambda _: register(), range(2)))

    with repository.engine.connect() as connection:
        rows = connection.execute(
            select(artifacts).where(artifacts.c.digest == digest)
        ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["metadata_json"] == {"source": "postgres-race"}
    repository.register_artifact(
        digest,
        size_bytes=7,
        storage_uri="test://postgres-race-artifact",
        media_type="application/vnd.scaffold-arena.trace+json",
        content_metadata={"artifact_role": "trace", "attempt_id": "attempt-two"},
    )
    with pytest.raises(ImmutableVersionConflict, match="different content location or size"):
        repository.register_artifact(
            digest,
            size_bytes=8,
            storage_uri="test://postgres-race-artifact",
            media_type="application/test",
            content_metadata={"source": "postgres-race"},
        )


def test_postgres_concurrent_execution_requests_replay_one_durable_execution(
    repository: ArenaRepository,
) -> None:
    project = repository.create_project("Postgres idempotency race")
    digest = uuid.uuid4().hex + uuid.uuid4().hex
    repository.register_artifact(digest, size_bytes=1, storage_uri="test://postgres-race-pack")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", digest)
    experiment = repository.create_experiment(
        project,
        pack,
        "concurrent execution",
        owner_approval="approved",
        experiment_id=_experiment_id(),
    )
    spec = freeze_protocol_experiment(
        ExperimentSpec(
            experiment_id=experiment,
            study_pack_id=pack,
            scenario_ids=("scenario-one",),
            harness_ids=("harness-one",),
            deterministic_weight=0.7,
            sampling=SamplingSpec(max_tokens=10),
            budgets=BudgetSpec(
                max_attempts=1,
                max_cost_usd=1,
                max_latency_seconds=5,
                max_tokens=10,
                max_tool_calls=0,
                max_context_tokens=10,
            ),
            owner_approval="approved",
        ),
        digest,
    )
    repository.freeze_experiment(
        experiment,
        expected_definition={},
        frozen_definition=spec.model_dump(mode="json"),
        spec_hash=str(spec.freeze_hash),
        study_pack_hash=digest,
    )
    harness = HarnessSpec(
        harness_id="harness-one",
        version="1",
        adapter="recorded",
        adapter_identity="recorded-one",
        adapter_digest=digest,
        timeout_seconds=5,
    )
    scenario = ScenarioSpec(
        scenario_id="scenario-one",
        title="Postgres idempotency race",
        task_family="fixture",
        prompt="Synthetic PostgreSQL race fixture.",
    )
    provenance = ExecutionProvenance(
        code_revision="postgres-race",
        code_hash=digest,
        runtime_image="postgres-race",
        runtime_image_hash=digest,
        environment_hash=digest,
        prompt_hash=digest,
        context_hash=digest,
        tool_hash=digest,
        source_refs=({"source_uri": "fixture://postgres-race", "content_hash": digest},),
        captured_at=datetime.now(UTC),
    )
    controller = ExperimentController(
        repository,
        harnesses={harness.harness_id: harness},
        scenario_specs={scenario.scenario_id: scenario},
    )
    barrier = Barrier(2)

    def create():
        barrier.wait()
        return controller.create_execution(
            project,
            spec,
            request_key="postgres-concurrent-key",
            request_payload={"fixture": "same"},
            provenance=provenance,
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        created = list(workers.map(lambda _: create(), range(2)))

    assert len({item.execution_id for item in created}) == 1
    assert sum(item.idempotent for item in created) == 1
    with repository.engine.connect() as connection:
        persisted = connection.execute(
            select(executions.c.id).where(executions.c.experiment_id == experiment)
        ).all()
    assert len(persisted) == 1


def test_postgres_cross_project_guards_and_immutable_versions(repository: ArenaRepository) -> None:
    one = repository.create_project("one")
    two = repository.create_project("two")
    digest = "c" * 64
    repository.register_artifact(digest, size_bytes=1, storage_uri="test://artifact")
    pack_one = repository.create_study_pack_version(one, "pack", "1.0.0", digest)
    pack_two = repository.create_study_pack_version(two, "pack", "1.0.0", digest)
    with pytest.raises(ImmutableVersionConflict):
        repository.create_study_pack_version(one, "pack", "1.0.0", digest)
    with pytest.raises(IntegrityError):
        repository.create_study_pack_version("missing", "pack", "1.0.0", digest)
    with pytest.raises(ValueError, match="study pack"):
        repository.create_experiment(two, pack_one, "cross-project")
    predecessor = repository.create_experiment(one, pack_one, "predecessor")
    with pytest.raises(ValueError, match="predecessor"):
        repository.create_experiment(two, pack_two, "cross-project-predecessor", predecessor_id=predecessor)
    with pytest.raises(ValueError, match="own predecessor"):
        repository.create_experiment(one, pack_one, "self-predecessor", experiment_id="self-predecessor", predecessor_id="self-predecessor")


def test_postgres_freeze_persists_frozen_definition_and_rejects_mismatch(repository: ArenaRepository) -> None:
    project = repository.create_project("Postgres frozen definition")
    digest = "e" * 64
    repository.register_artifact(digest, size_bytes=1, storage_uri="test://postgres-frozen-definition")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", digest)
    experiment = repository.create_experiment(project, pack, "experiment", owner_approval="approved", experiment_id=_experiment_id())
    definition, spec_hash = _frozen_definition(experiment, digest)
    repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash=digest)
    repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash=digest)
    with repository.engine.connect() as connection:
        row = connection.execute(select(experiments.c.definition, experiments.c.spec_hash, experiments.c.study_pack_hash).where(experiments.c.id == experiment)).one()
    assert row.definition == definition
    assert row.spec_hash == definition["freeze_hash"] == spec_hash
    assert row.study_pack_hash == definition["study_pack_hash"] == digest
    mismatch = dict(definition)
    mismatch["claim_ceiling"] = "different"
    with pytest.raises(FrozenExperimentError, match="different definition"):
        repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=mismatch, spec_hash=spec_hash, study_pack_hash=digest)


def test_postgres_freeze_rejects_stale_expected_definition(repository: ArenaRepository) -> None:
    project = repository.create_project("Postgres stale freeze")
    digest = "f" * 64
    repository.register_artifact(digest, size_bytes=1, storage_uri="test://postgres-stale-freeze")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", digest)
    expected = {"revision": "expected"}
    changed = {"revision": "changed"}
    experiment = repository.create_experiment(project, pack, "experiment", owner_approval="approved", definition=expected, experiment_id=_experiment_id())
    definition, spec_hash = _frozen_definition(experiment, digest)
    repository.update_experiment_definition(experiment, changed)
    with pytest.raises(FrozenExperimentError, match="definition changed before freeze"):
        repository.freeze_experiment(experiment, expected_definition=expected, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash=digest)
    with repository.engine.connect() as connection:
        row = connection.execute(select(experiments.c.definition, experiments.c.frozen_at).where(experiments.c.id == experiment)).one()
    assert row.definition == changed
    assert row.frozen_at is None


def test_postgres_event_sequence_is_monotonic_across_connections(repository: ArenaRepository) -> None:
    _, attempt, _, execution = _frozen_attempt(repository)
    with repository.engine.connect() as connection:
        episode_id = connection.execute(select(attempts.c.episode_id).where(attempts.c.id == attempt)).scalar_one()
    second_attempt = repository.create_attempt(episode_id, 1)
    with ThreadPoolExecutor(max_workers=8) as workers:
        sequences = list(workers.map(lambda index: repository.append_attempt_event(attempt if index % 2 else second_attempt, "tick"), range(24)))
    assert sorted(sequences[::2]) == list(range(1, 13))
    assert sorted(sequences[1::2]) == list(range(1, 13))
    assert [event["sequence"] for event in repository.list_attempt_events(attempt)] == list(range(1, 13))
    events = repository.list_execution_events_after(execution, 0)
    assert [event["execution_sequence"] for event in events] == list(range(1, 25))
    assert {event["attempt_id"] for event in events} == {attempt, second_attempt}


def test_postgres_cross_invocation_identity_admission_is_serialized(
    repository: ArenaRepository,
) -> None:
    request_project, _, _, request_execution = _frozen_attempt(repository)
    request_invocations, request_pair, request_now = _live_invocation_pair(
        repository, request_project, request_execution
    )
    request_lookup = Barrier(2, timeout=1)
    request_start = Barrier(2)
    request_advisory_seen = Event()

    def hold_request_lookup(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = " ".join(statement.split())
        if "pg_advisory_xact_lock" in normalized:
            request_advisory_seen.set()
        if (
            normalized.startswith("SELECT invocation_records.id FROM invocation_records")
            and "invocation_records.provider_request_id" in normalized
            and not request_advisory_seen.is_set()
        ):
            try:
                request_lookup.wait()
            except BrokenBarrierError:
                pass

    def observe_request(invocation: InvocationRecord) -> str:
        request_start.wait()
        try:
            InvocationRepository(repository).observe_provider_request(
                invocation,
                "postgres-cross-invocation-request",
                now=request_now,
            )
        except DuplicateProviderRequest:
            return "duplicate"
        return "observed"

    event.listen(repository.engine, "after_cursor_execute", hold_request_lookup)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            request_outcomes = list(workers.map(observe_request, request_pair))
    finally:
        event.remove(repository.engine, "after_cursor_execute", hold_request_lookup)

    assert sorted(request_outcomes) == ["duplicate", "observed"]
    assert request_advisory_seen.is_set()
    request_records = [
        request_invocations.get(invocation.invocation_id) for invocation in request_pair
    ]
    assert {record.provider_request_id for record in request_records} == {
        "postgres-cross-invocation-request"
    }
    assert sorted(record.admission_state for record in request_records) == [
        "current",
        "duplicate",
    ]
    assert {record.side_effect_state for record in request_records} == {"ambiguous"}

    result_project, _, _, result_execution = _frozen_attempt(repository)
    result_invocations, result_pair, result_now = _live_invocation_pair(
        repository, result_project, result_execution
    )
    result_lookup = Barrier(2, timeout=1)
    result_start = Barrier(2)
    result_advisory_seen = Event()
    result_digest = "e" * 64

    def hold_result_lookup(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = " ".join(statement.split())
        if "pg_advisory_xact_lock" in normalized:
            result_advisory_seen.set()
        if (
            normalized.startswith("SELECT invocation_records.id FROM invocation_records")
            and "invocation_records.provider_result_digest" in normalized
            and not result_advisory_seen.is_set()
        ):
            try:
                result_lookup.wait()
            except BrokenBarrierError:
                pass

    def admit_result(invocation: InvocationRecord) -> bool:
        result_start.wait()
        return InvocationRepository(repository).admit_terminal(
            invocation,
            result_digest=result_digest,
            terminal_outcome="completed",
            usage_state="reconciled",
            now=result_now,
        )

    event.listen(repository.engine, "after_cursor_execute", hold_result_lookup)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            result_outcomes = list(workers.map(admit_result, result_pair))
    finally:
        event.remove(repository.engine, "after_cursor_execute", hold_result_lookup)

    assert sorted(result_outcomes) == [False, True]
    assert result_advisory_seen.is_set()
    result_records = [
        result_invocations.get(invocation.invocation_id) for invocation in result_pair
    ]
    assert sum(record.provider_result_digest == result_digest for record in result_records) == 1
    assert sum(record.admission_state == "duplicate" for record in result_records) == 1
    duplicate = next(record for record in result_records if record.admission_state == "duplicate")
    assert duplicate.provider_result_digest is None
    assert duplicate.terminal_outcome is None
    assert duplicate.usage_state == "unknown"


def test_postgres_job_leases_skip_locked_expiry_heartbeat_cancel_finalize_and_retry(repository: ArenaRepository) -> None:
    project, first_attempt, _, execution = _frozen_attempt(repository)
    with repository.engine.connect() as connection:
        episode_id = connection.execute(
            select(attempts.c.episode_id).where(attempts.c.id == first_attempt)
        ).scalar_one()
    second_attempt = repository.create_attempt(episode_id, 1)
    expiry_attempt = repository.create_attempt(episode_id, 2)
    leases = JobLeaseRepository(repository)
    first = leases.enqueue(execution, attempt_id=first_attempt)
    second = leases.enqueue(execution, attempt_id=second_attempt)
    simultaneous_claimers = Barrier(2)

    def claim(owner: str):
        simultaneous_claimers.wait()
        return leases.claim(owner, lease_seconds=30, project_id=project)

    with ThreadPoolExecutor(max_workers=2) as workers:
        claimed = list(workers.map(claim, ["worker-a", "worker-b"]))
    claimed = [
        lease
        if lease is not None
        else leases.claim(owner, lease_seconds=30, project_id=project)
        for owner, lease in zip(("worker-a", "worker-b"), claimed, strict=True)
    ]
    assert {lease.id for lease in claimed if lease} == {first, second}
    active = next(lease for lease in claimed if lease is not None)
    assert leases.heartbeat(active.id, active.owner, lease_token=active.token, lease_seconds=30)
    assert leases.request_cancel(active.id)
    assert leases.cancel_requested(active.id, active.owner, lease_token=active.token) is True
    assert leases.complete(active.id, active.owner, lease_token=active.token) == "cancelled"

    queued_at = datetime.now(UTC)
    retry_input = AttemptInput.bind(
        ScenarioSpec(
            scenario_id="scenario-one",
            title="Postgres retry fixture",
            task_family="fixture",
            prompt="Synthetic retry fixture.",
        ),
        AttemptEnvelope(
            attempt_id=expiry_attempt,
            episode_id=episode_id,
            ordinal=3,
            provider_model="recorded",
            provider="test",
            harness_id="harness-one",
            factor_assignments={},
            budget=BudgetSpec(
                max_attempts=4,
                max_cost_usd=1,
                max_latency_seconds=5,
                max_tokens=10,
                max_tool_calls=0,
                max_context_tokens=10,
            ),
            provenance=ExecutionProvenance(
                code_revision="postgres-parity",
                code_hash="b" * 64,
                runtime_image="postgres-parity",
                runtime_image_hash="b" * 64,
                environment_hash="b" * 64,
                prompt_hash="b" * 64,
                context_hash="b" * 64,
                tool_hash="b" * 64,
                source_refs=(
                    {
                        "source_uri": "fixture://postgres-parity",
                        "content_hash": "b" * 64,
                    },
                ),
                captured_at=queued_at,
            ),
            request_hash="b" * 64,
            status="queued",
            queued_at=queued_at,
        ),
    )
    expiry_job = leases.enqueue(
        execution,
        attempt_id=expiry_attempt,
        payload={"attempt_input": retry_input.model_dump(mode="json")},
    )
    start = datetime.now(UTC)
    expired = leases.claim(
        "expired-worker", lease_seconds=1, now=start, project_id=project
    )
    assert expired and expired.id == expiry_job
    assert not leases.heartbeat(expiry_job, "expired-worker", lease_token=expired.token, lease_seconds=1, now=start + timedelta(seconds=2))
    reclaim_at = start + timedelta(seconds=1 + LEASE_RECLAIM_GRACE_SECONDS)
    assert leases.claim(
        "reclaim-scheduler", lease_seconds=30, now=reclaim_at, project_id=project
    ) is None
    reclaimed = leases.claim(
        "reclaimer",
        lease_seconds=30,
        now=reclaim_at + timedelta(seconds=LEASE_RECLAIM_BACKOFF_BASE_SECONDS),
        project_id=project,
    )
    assert reclaimed and reclaimed.id == expiry_job
    assert leases.fail(expiry_job, "reclaimer", lease_token=reclaimed.token, result_metadata={"failure_classification": "transient"}) == "failed"
    retry_attempt, retry_job = leases.retry(expiry_job)
    with repository.engine.connect() as connection:
        assert connection.execute(select(attempts.c.id).where(attempts.c.id == retry_attempt)).scalar_one() == retry_attempt
        assert connection.execute(select(jobs.c.id).where(jobs.c.id == retry_job)).scalar_one() == retry_job


def test_postgres_same_owner_stale_lease_cannot_mutate_reclaimed_job(repository: ArenaRepository) -> None:
    project, _, _, execution = _frozen_attempt(repository)
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(execution, attempt_id=None, kind="lease-fence-test")
    started = datetime.now(UTC) + timedelta(minutes=1)
    stale = leases.claim(
        "shared-owner",
        lease_seconds=1,
        now=started,
        kind="lease-fence-test",
        project_id=project,
    )
    assert stale is not None and stale.id == job
    reclaim_at = stale.expires_at + timedelta(seconds=LEASE_RECLAIM_GRACE_SECONDS)
    assert leases.reclaim_expired(now=reclaim_at) >= 1
    fresh = leases.claim(
        "shared-owner",
        lease_seconds=30,
        now=reclaim_at + timedelta(seconds=LEASE_RECLAIM_BACKOFF_BASE_SECONDS),
        kind="lease-fence-test",
        project_id=project,
    )
    assert fresh is not None and fresh.id == job and fresh.token != stale.token
    assert not leases.heartbeat(
        job,
        "shared-owner",
        lease_token=stale.token,
        lease_seconds=30,
        now=fresh.expires_at - timedelta(seconds=1),
    )
    assert leases.finalize_auxiliary(
        job,
        "shared-owner",
        lease_token=stale.token,
        outcome="completed",
        now=fresh.expires_at - timedelta(seconds=1),
    ) is None
    with repository.engine.connect() as connection:
        row = connection.execute(select(jobs).where(jobs.c.id == job)).mappings().one()
    assert row["status"] == "running"
    assert row["lease_token"] == fresh.token


def test_postgres_stale_evaluator_cannot_publish_after_same_owner_reclaim(repository: ArenaRepository) -> None:
    project, attempt, _, execution = _frozen_attempt(repository)
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(execution, attempt_id=attempt, kind="evaluation")
    started = datetime.now(UTC) + timedelta(minutes=1)
    stale = leases.claim(
        "shared-evaluator",
        lease_seconds=1,
        now=started,
        kind="evaluation",
        project_id=project,
    )
    assert stale is not None and stale.id == job
    reclaim_at = stale.expires_at + timedelta(seconds=LEASE_RECLAIM_GRACE_SECONDS)
    assert leases.reclaim_expired(now=reclaim_at) >= 1
    fresh = leases.claim(
        "shared-evaluator",
        lease_seconds=30,
        now=reclaim_at + timedelta(seconds=LEASE_RECLAIM_BACKOFF_BASE_SECONDS),
        kind="evaluation",
        project_id=project,
    )
    assert fresh is not None and fresh.token != stale.token
    with pytest.raises(ImmutableEvaluationConflict, match="lease is no longer current"):
        repository.create_evaluation_record(
            project,
            record={
                "id": "evaluation-stale",
                "attempt_id": attempt,
                "project_id": project,
                "evaluator": "test-evaluator",
                "result": {},
            },
            lease_job_id=stale.id,
            lease_owner=stale.owner,
            lease_token=stale.token,
        )
    with repository.engine.connect() as connection:
        assert connection.execute(select(jobs.c.lease_token).where(jobs.c.id == job)).scalar_one() == fresh.token


def test_postgres_project_scoped_leases_are_isolated_under_cross_project_races(repository: ArenaRepository) -> None:
    project_one, attempt_one, _, execution_one = _frozen_attempt(repository)
    project_two, attempt_two, _, execution_two = _frozen_attempt(repository)
    leases = JobLeaseRepository(repository)
    attempt_jobs = {
        project_one: leases.enqueue(execution_one, attempt_id=attempt_one, kind="attempt"),
        project_two: leases.enqueue(execution_two, attempt_id=attempt_two, kind="attempt"),
    }
    evaluation_jobs = {
        project_one: leases.enqueue(execution_one, attempt_id=attempt_one, kind="evaluation"),
        project_two: leases.enqueue(execution_two, attempt_id=attempt_two, kind="evaluation"),
    }

    def race(kind: str) -> dict[str, str]:
        barrier = Barrier(2)

        def claim(project_id: str) -> tuple[str, str | None]:
            barrier.wait()
            lease = leases.claim(
                f"{kind}-{project_id[-6:]}",
                lease_seconds=30,
                kind=kind,
                project_id=project_id,
            )
            return project_id, lease.id if lease else None

        with ThreadPoolExecutor(max_workers=2) as workers:
            claimed = dict(workers.map(claim, (project_one, project_two)))
        return {project_id: job_id for project_id, job_id in claimed.items() if job_id}

    assert race("attempt") == attempt_jobs
    assert race("evaluation") == evaluation_jobs
