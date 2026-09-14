from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from adapters_v1 import (
    AdapterRegistry,
    ArtifactRef,
    AttemptInput,
    CommandJsonlAdapter,
    HttpRpcAdapter,
    ProviderUsage,
    RecordedAdapter,
    ResultBundle,
)
from artifacts_v1.store import LocalArtifactStore
from execution_v1 import (
    BudgetReservationService,
    CentralPriceResolver,
    DurableEventReader,
    DurableWorker,
    ExecutionProvenance,
    ExperimentController,
    PriceQuote,
    StateOracleDecision,
)
from execution_v1.currency import currency
from execution_v1.worker import (
    MissingOutputEvidence,
    MissingUsageEvidence,
    UsageMismatch,
)
from persistence_v1 import (
    ArenaRepository,
    FrozenExperimentError,
    create_persistence_engine,
    metadata,
)
from persistence_v1.jobs import (
    LEASE_RECLAIM_BACKOFF_BASE_SECONDS,
    LEASE_RECLAIM_BACKOFF_CAP_SECONDS,
    LEASE_RECLAIM_GRACE_SECONDS,
    MAX_LEASE_GENERATIONS,
    JobLeaseRepository,
)
from persistence_v1.schema import attempt_events, attempts, episodes, executions, jobs
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from protocol_v1.models import (
    AttemptEnvelope,
    BudgetSpec,
    ExperimentSpec,
    FactorSpec,
    FaultMetadata,
    HarnessSchemaHashes,
    HarnessSpec,
    ManipulationCheck,
    SamplingSpec,
    ScenarioSpec,
    TraceEvent,
    TreatmentMutation,
)
from protocol_v1.study_pack import freeze_experiment

HASH_A = "a" * 64
HASH_B = "b" * 64
NOW = datetime.now(UTC)


def completed_result(**values: object) -> ResultBundle:
    """A completed result always carries its canonical response bytes."""
    attempt_id = str(values["attempt_id"])
    response_bytes = canonical_json({"response": "fixture", "attempt_id": attempt_id})
    response_hash = sha256_bytes(response_bytes)
    values.setdefault("response_hash", response_hash)
    values.setdefault("response_artifact_id", "response")
    values.setdefault(
        "artifacts",
        (
            ArtifactRef(
                artifact_id="response",
                media_type="application/json",
                sha256=str(values["response_hash"]),
                content=response_bytes if values["response_hash"] == response_hash else None,
                uri=None if values["response_hash"] == response_hash else "fixture://response",
            ),
        ),
    )
    return ResultBundle(**values)


def trace_event(attempt_id: str, episode_id: str, *, sequence: int = 0) -> TraceEvent:
    return TraceEvent(
        trace_id=f"trace-{attempt_id}-{sequence}",
        episode_id=episode_id,
        attempt_id=attempt_id,
        sequence=sequence,
        actor="model",
        event_type="response",
        timestamp=NOW,
        monotonic_time=sequence,
        payload={"fixture": attempt_id},
        payload_hash=HASH_A,
    )


def run_recorded_attempt(
    repository: ArenaRepository,
    tmp_path: Path,
    result: ResultBundle,
    *,
    events: tuple[TraceEvent, ...] = (),
    state_oracle=None,
    envelope: AttemptEnvelope | None = None,
    claim_eligibility: str = "fixture_only",
    harness_spec: HarnessSpec | None = None,
) -> tuple[object, dict[str, object], LocalArtifactStore]:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        execution, 0, episode_id="episode-one", scenario_id="scenario-one",
    )
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    envelope = envelope or live_envelope(
        provider_model="recorded", provider="test", endpoint_id=None, pinned_endpoint_digest=None,
    )
    adapter = RecordedAdapter(
        adapter_id="recorded-one", adapter_digest=HASH_A, results={"attempt-one": result},
        events={"attempt-one": events},
    )
    adapter._capabilities = adapter._capabilities.model_copy(update={
        "claim_eligibility": claim_eligibility,
        "config_schema_hash": HASH_A if claim_eligibility != "fixture_only" else None,
    })
    registry = AdapterRegistry()
    asyncio.run(registry.install_trusted(adapter, HASH_A))
    JobLeaseRepository(repository).enqueue(
        execution,
        attempt_id="attempt-one",
        payload={
            "attempt_input": AttemptInput.bind(
                scenario(
                    "scenario-one",
                    **({"final_state_oracle": {"oracle_id": "state-one", "kind": "predicate", "expected": True, "description": "fixture"}} if state_oracle else {}),
                ),
                envelope,
            ).model_dump(mode="json"),
            "harness": (harness_spec or harness()).model_dump(mode="json"),
        },
    )
    store = LocalArtifactStore(tmp_path / "artifacts")
    outcome = asyncio.run(DurableWorker(repository, registry, store, state_oracle=state_oracle).run_once("worker"))
    with repository.engine.connect() as conn:
        row = dict(conn.execute(attempts.select().where(attempts.c.id == "attempt-one")).mappings().one())
    return outcome, row, store


@pytest.fixture
def repository(tmp_path: Path) -> ArenaRepository:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    return ArenaRepository(engine)


def harness() -> HarnessSpec:
    return HarnessSpec(
        harness_id="harness-one",
        version="1",
        adapter="recorded",
        adapter_identity="recorded-one",
        adapter_digest=HASH_A,
        timeout_seconds=5,
    )


def scenario(scenario_id: str = "scenario-one", **updates: object) -> ScenarioSpec:
    values: dict[str, object] = {
        "scenario_id": scenario_id,
        "title": "Scenario",
        "task_family": "fixture",
        "prompt": "Synthetic fixture prompt.",
    }
    values.update(updates)
    return ScenarioSpec(**values)


def scenario_specs() -> dict[str, ScenarioSpec]:
    return {
        item.scenario_id: item
        for item in (scenario("scenario-one"), scenario("scenario-two"))
    }


def attempt_input(
    envelope: AttemptEnvelope, scenario_id: str = "scenario-one"
) -> AttemptInput:
    return AttemptInput.bind(scenario(scenario_id), envelope)


def frozen_spec(
    *, randomization_blocks: tuple[dict[str, object], ...] = ()
) -> ExperimentSpec:
    return freeze_experiment(
        ExperimentSpec(
            experiment_id="experiment-one",
            study_pack_id="pack-one",
            scenario_ids=("scenario-one", "scenario-two"),
            harness_ids=("harness-one",),
            repetitions=2,
            deterministic_weight=0.7,
            sampling=SamplingSpec(max_tokens=10),
            budgets=BudgetSpec(
                max_attempts=2,
                max_cost_usd=1,
                max_latency_seconds=5,
                max_tokens=10,
                max_tool_calls=0,
                max_context_tokens=10,
            ),
            owner_approval="approved",
            randomization_blocks=randomization_blocks,
        ),
        HASH_A,
    )


def provenance() -> ExecutionProvenance:
    return ExecutionProvenance(
        code_revision="fixture",
        code_hash=HASH_A,
        runtime_image="fixture",
        runtime_image_hash=HASH_A,
        environment_hash=HASH_A,
        prompt_hash=HASH_A,
        context_hash=HASH_A,
        tool_hash=HASH_A,
        source_refs=({"source_uri": "fixture://source", "content_hash": HASH_A},),
        captured_at=NOW,
    )


def prepare_frozen(repository: ArenaRepository) -> None:
    repository.create_project("Test", project_id="project-one")
    repository.register_artifact(HASH_A, size_bytes=1, storage_uri="local://pack")
    pack = repository.create_study_pack_version(
        "project-one", "pack", "1.0.0", HASH_A, study_pack_id="pack-one"
    )
    frozen = frozen_spec().model_dump(mode="json")
    expected = {**frozen, "frozen": False, "freeze_hash": None, "frozen_at": None}
    repository.create_experiment(
        "project-one",
        pack,
        "experiment",
        owner_approval="approved",
        experiment_id="experiment-one",
        definition=expected,
    )
    repository.freeze_experiment(
        "experiment-one",
        expected_definition=expected,
        frozen_definition=frozen,
        spec_hash=str(frozen["freeze_hash"]),
        study_pack_hash=HASH_A,
    )


def provider_usage(**updates: object) -> ProviderUsage:
    values: dict[str, object] = {
        "evidence_source": "provider_reported",
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
        "context_tokens": 2,
        "tool_calls": 0,
        "cached_input_tokens": 0,
        "service_tier": "standard",
        "billing_profile": "standard",
        "provider_usage_digest": HASH_A,
        "observed_provider_version": "2026-08-14",
        "observed_endpoint_digest": HASH_A,
    }
    values.update(updates)
    return ProviderUsage(**values)


def live_envelope(**updates: object) -> AttemptEnvelope:
    values: dict[str, object] = {
        "attempt_id": "attempt-one",
        "episode_id": "episode-one",
        "ordinal": 1,
        "provider_model": "gpt-4.1",
        "provider": "openai",
        "endpoint_id": "endpoint-one",
        "pinned_endpoint_digest": HASH_A,
        "harness_id": "harness-one",
        "factor_assignments": {},
        "budget": BudgetSpec(
            max_attempts=1,
            max_cost_usd=1,
            max_latency_seconds=5,
            max_tokens=5,
            max_tool_calls=0,
            max_context_tokens=2,
        ),
        "provenance": provenance(),
        "request_hash": HASH_A,
        "status": "queued",
        "queued_at": NOW,
    }
    values.update(updates)
    return AttemptEnvelope(**values)


def test_controller_expands_deterministically_and_is_idempotent(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    controller = ExperimentController(
        repository,
        harnesses={"harness-one": harness()},
        scenario_specs=scenario_specs(),
    )
    first = controller.create_execution(
        "project-one",
        frozen_spec(),
        request_key="same",
        request_payload={"x": 1},
        provenance=provenance(),
    )
    same = controller.create_execution(
        "project-one",
        frozen_spec(),
        request_key="same",
        request_payload={"x": 1},
        provenance=provenance(),
    )
    assert len(first.episode_ids) == 4
    assert same.execution_id == first.execution_id and same.idempotent
    with pytest.raises(ValueError, match="different request"):
        controller.create_execution(
            "project-one",
            frozen_spec(),
            request_key="same",
            request_payload={"x": 2},
            provenance=provenance(),
        )


def test_controller_replays_one_execution_under_concurrent_same_key_requests(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    controller = ExperimentController(
        repository,
        harnesses={"harness-one": harness()},
        scenario_specs=scenario_specs(),
    )
    barrier = Barrier(2)

    def create() -> object:
        barrier.wait()
        return controller.create_execution(
            "project-one",
            frozen_spec(),
            request_key="concurrent-key",
            request_payload={"x": 1},
            provenance=provenance(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = list(executor.map(lambda _: create(), range(2)))

    assert len({item.execution_id for item in created}) == 1
    assert sum(item.idempotent for item in created) == 1
    with repository.engine.connect() as conn:
        executions_for_experiment = conn.execute(
            select(executions.c.id).where(executions.c.experiment_id == "experiment-one")
        ).all()
    assert len(executions_for_experiment) == 1


def test_controller_persists_explicit_analysis_units_for_factors_repetitions_and_stress_pairs(
    repository: ArenaRepository,
) -> None:
    specification = freeze_experiment(
        ExperimentSpec(
            experiment_id="experiment-one",
            study_pack_id="pack-one",
            scenario_ids=("clean-one", "stress-one"),
            harness_ids=("harness-one",),
            repetitions=2,
            deterministic_weight=0.7,
            sampling=SamplingSpec(max_tokens=10),
            budgets=BudgetSpec(
                max_attempts=2,
                max_cost_usd=1,
                max_latency_seconds=5,
                max_tokens=10,
                max_tool_calls=0,
                max_context_tokens=10,
            ),
            owner_approval="approved",
            factors=(
                FactorSpec(
                    factor_id="enabled",
                    kind="binary",
                    levels=(False, True),
                    baseline=False,
                    description="toggle",
                    treatment_mutations=(
                        TreatmentMutation(
                            target="toggle", operation="enable", level=True
                        ),
                    ),
                    manipulation_checks=(
                        ManipulationCheck(
                            factor_id="enabled", expected_value=False, oracle="fixture"
                        ),
                    ),
                ),
            ),
        ),
        HASH_A,
    )
    repository.create_project("Test", project_id="project-one")
    repository.register_artifact(HASH_A, size_bytes=1, storage_uri="local://pack")
    pack = repository.create_study_pack_version(
        "project-one", "pack", "1.0.0", HASH_A, study_pack_id="pack-one"
    )
    frozen = specification.model_dump(mode="json")
    expected = {**frozen, "frozen": False, "freeze_hash": None, "frozen_at": None}
    repository.create_experiment(
        "project-one",
        pack,
        "experiment",
        owner_approval="approved",
        experiment_id="experiment-one",
        definition=expected,
    )
    repository.freeze_experiment(
        "experiment-one",
        expected_definition=expected,
        frozen_definition=frozen,
        spec_hash=str(frozen["freeze_hash"]),
        study_pack_hash=HASH_A,
    )
    scenarios = {
        "clean-one": scenario(
            "clean-one",
            cluster_id="cluster-one",
            pair_id="pair-one",
            paired_scenario_id="stress-one",
        ),
        "stress-one": scenario(
            "stress-one",
            cluster_id="cluster-one",
            variant="stress",
            pair_id="pair-one",
            paired_scenario_id="clean-one",
            fault_metadata=FaultMetadata(
                fault_id="noise", category="context", description="noise"
            ),
        ),
    }
    created = ExperimentController(
        repository, harnesses={"harness-one": harness()}, scenario_specs=scenarios
    ).create_execution(
        "project-one",
        specification,
        request_key="analysis-units",
        provenance=provenance(),
    )
    with repository.engine.connect() as conn:
        rows = (
            conn.execute(
                select(episodes.c.metadata_json, attempts.c.request_metadata)
                .join(attempts, attempts.c.episode_id == episodes.c.id)
                .where(episodes.c.id.in_(created.episode_ids))
            )
            .mappings()
            .all()
        )
    assert len(rows) == 8
    by_repetition: dict[int, list[dict[str, object]]] = {}
    for row in rows:
        metadata = dict(row["metadata_json"])
        assert {
            "scenario_variant",
            "scenario_pair_id",
            "scenario_cluster_id",
            "repetition_index",
            "analysis_pair_id",
        }.issubset(metadata)
        metadata["factor_assignment"] = row["request_metadata"]["envelope"][
            "factor_assignments"
        ]["enabled"]
        by_repetition.setdefault(metadata["repetition_index"], []).append(metadata)
    assert set(by_repetition) == {0, 1}
    assert {row["analysis_pair_id"] for row in by_repetition[0]} != {
        row["analysis_pair_id"] for row in by_repetition[1]
    }
    for units in by_repetition.values():
        assert {row["scenario_variant"] for row in units} == {"clean", "stress"}
        assert {row["scenario_pair_id"] for row in units} == {"pair-one"}
        assert len({row["analysis_pair_id"] for row in units}) == 1
        for variant in ("clean", "stress"):
            assert {
                row["factor_assignment"]
                for row in units
                if row["scenario_variant"] == variant
            } == {False, True}


def test_provenance_is_required_bound_and_cluster_blocks_fail_closed(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    controller = ExperimentController(
        repository,
        harnesses={"harness-one": harness()},
        scenario_specs=scenario_specs(),
    )
    with pytest.raises(ValueError, match="code_hash"):
        ExecutionProvenance(
            code_revision="fixture",
            code_hash="bad",
            runtime_image="fixture",
            runtime_image_hash=HASH_A,
            environment_hash=HASH_A,
            prompt_hash=HASH_A,
            context_hash=HASH_A,
            tool_hash=HASH_A,
            source_refs=({"source_uri": "fixture://source", "content_hash": HASH_A},),
            captured_at=NOW,
        )
    with pytest.raises(TypeError):
        controller.create_execution("project-one", frozen_spec(), request_key="missing")  # type: ignore[call-arg]
    created = controller.create_execution(
        "project-one", frozen_spec(), request_key="bound", provenance=provenance()
    )
    with repository.engine.connect() as conn:
        metadata = (
            conn.execute(
                attempts.select().where(attempts.c.episode_id == created.episode_ids[0])
            )
            .mappings()
            .one()["request_metadata"]
        )
    assert metadata["envelope"]["provenance"]["code_hash"] == HASH_A
    assert metadata["envelope"]["provenance"]["source_refs"] == [
        {"source_uri": "fixture://source", "content_hash": HASH_A}
    ]
    blocked = frozen_spec(
        randomization_blocks=(
            {"block_id": "cluster-one", "unit": "cluster", "values": ("cluster-a",)},
        )
    )
    with pytest.raises(FrozenExperimentError, match="frozen hashes"):
        ExperimentController(
            repository,
            harnesses={"harness-one": harness()},
            scenario_specs=scenario_specs(),
        ).create_execution(
            "project-one", blocked, request_key="cluster", provenance=provenance()
        )


def test_controller_snapshots_exact_scenarios_and_rejects_missing_or_mismatched_specs(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    with pytest.raises(ValueError, match="scenario specifications"):
        ExperimentController(
            repository, harnesses={"harness-one": harness()}
        ).create_execution(
            "project-one",
            frozen_spec(),
            request_key="missing-scenario",
            provenance=provenance(),
        )
    mismatched = scenario_specs()
    mismatched["scenario-one"] = scenario("scenario-two")
    with pytest.raises(ValueError, match="key does not match"):
        ExperimentController(
            repository, harnesses={"harness-one": harness()}, scenario_specs=mismatched
        ).create_execution(
            "project-one",
            frozen_spec(),
            request_key="mismatched-scenario",
            provenance=provenance(),
        )
    original = scenario_specs()
    controller = ExperimentController(
        repository, harnesses={"harness-one": harness()}, scenario_specs=original
    )
    created = controller.create_execution(
        "project-one", frozen_spec(), request_key="snapshot", provenance=provenance()
    )
    original["scenario-one"].prompt = "mutated after enqueue"
    with repository.engine.connect() as conn:
        payloads = (
            conn.execute(jobs.select().where(jobs.c.id.in_(created.job_ids)))
            .mappings()
            .all()
        )
    assert payloads
    assert all(
        set(payload) == {"attempt_input", "harness", "aggregate_budget"}
        for payload in (row["payload"] for row in payloads)
    )
    assert any(
        row["payload"]["attempt_input"]["scenario"]["prompt"]
        == "Synthetic fixture prompt."
        for row in payloads
    )


def test_controller_rejects_nested_mutation_of_frozen_spec(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    mutated = frozen_spec()
    mutated.budgets.max_tokens = 99
    with pytest.raises(FrozenExperimentError, match="content does not match"):
        ExperimentController(
            repository,
            harnesses={"harness-one": harness()},
            scenario_specs=scenario_specs(),
        ).create_execution(
            "project-one",
            mutated,
            request_key="mutated",
            provenance=provenance(),
        )


def test_attempt_input_bind_snapshots_children_and_revalidation_rejects_nested_mutation() -> (
    None
):
    source = scenario()
    envelope = live_envelope()
    bound = AttemptInput.bind(source, envelope)
    source.prompt = "mutated source"
    envelope.factor_assignments["switch"] = True
    assert bound.scenario.prompt == "Synthetic fixture prompt."
    assert bound.attempt.factor_assignments == {}
    bound.scenario.prompt = "tampered binding"
    with pytest.raises(ValidationError, match="scenario_digest"):
        AttemptInput.model_validate_json(canonical_json(bound.model_dump(mode="json")))


def test_leasing_reclaims_expired_and_rejects_wrong_owner(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(execution, attempt_id=None)
    claimed_at = datetime.now(UTC)
    first = leases.claim("one", lease_seconds=1, now=claimed_at)
    assert first and first.id == job
    assert not leases.heartbeat(job, "two", lease_token=first.token, lease_seconds=1, now=NOW)
    reclaim_at = claimed_at + timedelta(seconds=1 + LEASE_RECLAIM_GRACE_SECONDS)
    assert leases.reclaim_expired(now=reclaim_at - timedelta(microseconds=1)) == 0
    assert leases.reclaim_expired(now=reclaim_at) == 1
    assert leases.claim("two", lease_seconds=1, now=reclaim_at) is None
    assert leases.claim(
        "two",
        lease_seconds=1,
        now=reclaim_at + timedelta(seconds=LEASE_RECLAIM_BACKOFF_BASE_SECONDS),
    )


def test_same_owner_reclaim_cannot_heartbeat_or_finalize_a_stale_generation(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(execution, attempt_id=None)
    started = datetime.now(UTC) + timedelta(minutes=1)
    stale = leases.claim("shared-owner", lease_seconds=1, now=started)
    assert stale is not None
    reclaim_at = stale.expires_at + timedelta(seconds=LEASE_RECLAIM_GRACE_SECONDS)
    assert leases.reclaim_expired(now=reclaim_at) == 1
    fresh = leases.claim(
        "shared-owner",
        lease_seconds=10,
        now=reclaim_at + timedelta(seconds=LEASE_RECLAIM_BACKOFF_BASE_SECONDS),
    )
    assert fresh is not None and fresh.token != stale.token
    assert not leases.heartbeat(
        stale.id,
        stale.owner,
        lease_token=stale.token,
        lease_seconds=10,
        now=fresh.expires_at - timedelta(seconds=1),
    )
    assert leases.finalize_auxiliary(
        stale.id,
        stale.owner,
        lease_token=stale.token,
        outcome="completed",
        now=fresh.expires_at - timedelta(seconds=1),
    ) is None
    with repository.engine.connect() as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == job)).mappings().one()
    assert row["status"] == "running"
    assert row["lease_token"] == fresh.token


def test_lease_reclaim_grace_backoff_and_generation_cap_terminalize_truthfully(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0, episode_id="lease-episode")
    attempt = repository.create_attempt(episode, 0, attempt_id="lease-attempt")
    leases = JobLeaseRepository(repository)
    now = datetime(2026, 8, 22, tzinfo=UTC)
    job = leases.enqueue(execution, attempt_id=attempt, available_at=now)
    lease = leases.claim("worker-1", lease_seconds=1, now=now)
    assert lease and lease.id == job and lease.attempt_count == 1

    observed_backoffs: list[float] = []
    for generation in range(1, MAX_LEASE_GENERATIONS + 1):
        reclaim_at = lease.expires_at + timedelta(seconds=LEASE_RECLAIM_GRACE_SECONDS)
        assert leases.reclaim_expired(now=reclaim_at - timedelta(microseconds=1)) == 0
        if generation == 1:
            # claim() and reclaim_expired() share the same reclaim policy.
            assert leases.claim("worker-2", lease_seconds=1, now=reclaim_at) is None
        else:
            assert leases.reclaim_expired(now=reclaim_at) == 1

        with repository.engine.connect() as conn:
            row = conn.execute(jobs.select().where(jobs.c.id == job)).mappings().one()

        if generation == MAX_LEASE_GENERATIONS:
            assert row["status"] == "failed"
            break

        assert row["status"] == "queued"
        delay = min(
            LEASE_RECLAIM_BACKOFF_BASE_SECONDS * (2 ** (generation - 1)),
            LEASE_RECLAIM_BACKOFF_CAP_SECONDS,
        )
        observed_backoffs.append(delay)
        available_at = reclaim_at + timedelta(seconds=delay)
        persisted_available_at = row["available_at"]
        if persisted_available_at.tzinfo is None:
            persisted_available_at = persisted_available_at.replace(tzinfo=UTC)
        assert persisted_available_at == available_at
        assert leases.claim("too-early", lease_seconds=1, now=available_at - timedelta(microseconds=1)) is None
        lease = leases.claim(f"worker-{generation + 1}", lease_seconds=1, now=available_at)
        assert lease and lease.attempt_count == generation + 1

    assert observed_backoffs[-1] == LEASE_RECLAIM_BACKOFF_CAP_SECONDS
    assert observed_backoffs[-2] == LEASE_RECLAIM_BACKOFF_CAP_SECONDS
    with repository.engine.connect() as conn:
        attempt_row = conn.execute(attempts.select().where(attempts.c.id == attempt)).mappings().one()
        execution_row = conn.execute(executions.select().where(executions.c.id == execution)).mappings().one()
        events = conn.execute(
            select(attempt_events.c.event_type, attempt_events.c.payload).where(
                attempt_events.c.attempt_id == attempt,
            ).order_by(attempt_events.c.sequence)
        ).mappings().all()
    assert attempt_row["status"] == "incomplete"
    assert attempt_row["result_metadata"]["error_code"] == "lease_generation_exhausted"
    assert attempt_row["result_metadata"]["lease_generation"] == MAX_LEASE_GENERATIONS
    assert attempt_row["result_metadata"]["max_lease_generations"] == MAX_LEASE_GENERATIONS
    assert execution_row["status"] == "failed"
    assert [event["event_type"] for event in events] == ["lease_generation_exhausted", "terminal"]
    assert events[-1]["payload"]["winner"] == "failed"
    assert leases.claim("never-again", lease_seconds=1, now=now + timedelta(days=1)) is None


def test_project_scoped_claim_does_not_reclaim_or_lease_foreign_work(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    repository.create_project("Other", project_id="project-two")
    execution = repository.create_execution("experiment-one")
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(execution, attempt_id=None)
    claimed_at = datetime.now(UTC)
    foreign = leases.claim("foreign-worker", lease_seconds=1, now=claimed_at)

    assert foreign and foreign.id == job
    assert leases.claim(
        "scoped-worker",
        lease_seconds=30,
        now=claimed_at + timedelta(seconds=2),
        project_id="project-two",
    ) is None
    with repository.engine.connect() as conn:
        row = conn.execute(jobs.select().where(jobs.c.id == job)).mappings().one()
    assert row["status"] == "running"
    assert row["lease_owner"] == "foreign-worker"


def test_event_reset_and_conservative_cost(repository: ArenaRepository) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0)
    attempt = repository.create_attempt(episode, 0, attempt_id="attempt-one")
    repository.append_attempt_event(attempt, "one")
    repository.append_attempt_event(attempt, "two")
    read = DurableEventReader(repository).read(
        attempt, after_sequence=0, retention_floor=2
    )
    assert (
        read.reset
        and read.snapshot
        and [item["sequence"] for item in read.events] == [2]
    )
    service = BudgetReservationService(repository)
    ledger = service.reserve(execution, attempt, model_id="recorded", max_cost_usd=1)
    assert service.unknown(ledger).status == "unknown"
    assert (
        service.reconcile(
            ledger,
            input_tokens=1,
            output_tokens=2,
            actual_cost_usd=0.2,
            provider_usage_digest="bad",
            price_catalog_revision="prices",
        ).status
        == "mismatch"
    )
    assert (
        service.reconcile(
            ledger,
            input_tokens=1,
            output_tokens=2,
            actual_cost_usd=0.2,
            provider_usage_digest="c" * 64,
            price_catalog_revision="prices",
            expected_cost_usd=0.2,
            usage=ProviderUsage(
                evidence_source="provider_reported",
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                context_tokens=1,
                tool_calls=0,
            ),
        ).status
        == "reconciled"
    )


class FailingOracle:
    def evaluate(self, scenario, oracle, attempt, result):
        return StateOracleDecision(
            "failed", "state did not match", {"oracle": oracle.oracle_id}
        )


class UpgradingOracle:
    def evaluate(self, scenario, oracle, attempt, result):
        return StateOracleDecision(
            "completed", "authoritative upgrade", {"authoritative_terminal_evidence": True}
        )


class SlowRecordedAdapter(RecordedAdapter):
    async def execute_attempt(self, prepared):
        await asyncio.sleep(0.2)
        return await super().execute_attempt(prepared)


class TimeoutRecordedAdapter(RecordedAdapter):
    async def execute_attempt(self, prepared):
        await asyncio.sleep(1.2)
        return await super().execute_attempt(prepared)


class DelayedTraceRecordedAdapter(RecordedAdapter):
    async def stream_events(self, prepared):
        attempt = self._attempt(prepared).attempt
        await asyncio.sleep(0.02)
        yield TraceEvent(
            trace_id="trace-one",
            episode_id=attempt.episode_id,
            attempt_id=attempt.attempt_id,
            sequence=0,
            actor="model",
            event_type="response",
            timestamp=NOW,
            monotonic_time=0,
            payload={"late": True},
            payload_hash=HASH_A,
        )


class NonterminatingTraceRecordedAdapter(RecordedAdapter):
    async def stream_events(self, prepared):
        attempt = self._attempt(prepared).attempt
        yield TraceEvent(
            trace_id="trace-partial",
            episode_id=attempt.episode_id,
            attempt_id=attempt.attempt_id,
            sequence=0,
            actor="model",
            event_type="response",
            timestamp=NOW,
            monotonic_time=0,
            payload={"partial": True},
            payload_hash=HASH_A,
        )
        while True:
            await asyncio.sleep(10)
            if False:
                yield None


def test_worker_rejects_missing_swapped_and_extra_attempt_inputs_before_adapter_execution(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)
    registry = AdapterRegistry()
    results = {
        f"attempt-{label}": completed_result(
            attempt_id=f"attempt-{label}",
            terminal_outcome="completed",
            completed_at=NOW + timedelta(seconds=1),
            usage=ProviderUsage(
                evidence_source="fixture_recorded",
                total_tokens=1,
                context_tokens=1,
                tool_calls=0,
            ),
        )
        for label in ("missing", "swapped", "extra")
    }
    adapter = RecordedAdapter(
        adapter_id="recorded-one", adapter_digest=HASH_A, results=results
    )
    asyncio.run(registry.install_trusted(adapter, HASH_A))
    for ordinal, label in enumerate(("missing", "swapped", "extra")):
        execution = repository.create_execution("experiment-one")
        episode_id, attempt_id = f"episode-{label}", f"attempt-{label}"
        repository.create_episode(
            execution, ordinal, episode_id=episode_id, scenario_id="scenario-one"
        )
        repository.create_attempt(episode_id, 0, attempt_id=attempt_id)
        envelope = live_envelope(
            attempt_id=attempt_id,
            episode_id=episode_id,
            provider_model="recorded",
            provider="test",
            endpoint_id=None,
            pinned_endpoint_digest=None,
        )
        payload: dict[str, object] = {"harness": harness().model_dump(mode="json")}
        if label == "swapped":
            payload["attempt_input"] = AttemptInput.bind(
                scenario("scenario-two"), envelope
            ).model_dump(mode="json")
        elif label == "extra":
            raw = attempt_input(envelope).model_dump(mode="json")
            raw["untrusted"] = True
            payload["attempt_input"] = raw
        JobLeaseRepository(repository).enqueue(
            execution, attempt_id=attempt_id, payload=payload
        )
        outcome = asyncio.run(
            DurableWorker(
                repository, registry, LocalArtifactStore(tmp_path / label)
            ).run_once("worker")
        )
        assert outcome and outcome.status == "failed"
    assert not adapter._attempts


def test_worker_persists_cleanup_and_oracle_wins(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        execution, 0, episode_id="episode-one", scenario_id="scenario-one"
    )
    attempt_id = "attempt-one"
    repository.create_attempt(episode, 0, attempt_id=attempt_id)
    envelope = AttemptEnvelope(
        attempt_id=attempt_id,
        episode_id=episode,
        ordinal=1,
        provider_model="recorded",
        provider="test",
        harness_id="harness-one",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=1,
            max_cost_usd=1,
            max_latency_seconds=5,
            max_tokens=10,
            max_tool_calls=0,
            max_context_tokens=10,
        ),
        provenance=provenance(),
        request_hash=HASH_A,
        status="queued",
        queued_at=NOW,
    )
    result = completed_result(
        attempt_id=attempt_id,
        terminal_outcome="completed",
        completed_at=datetime.now(UTC) + timedelta(seconds=1),
        usage=ProviderUsage(
            evidence_source="fixture_recorded",
            total_tokens=1,
            context_tokens=1,
            tool_calls=0,
        ),
    )
    adapter = RecordedAdapter(
        adapter_id="recorded-one", adapter_digest=HASH_A, results={attempt_id: result},
        events={attempt_id: (trace_event(attempt_id, episode),)},
    )
    registry = AdapterRegistry()
    asyncio.run(registry.install_trusted(adapter, HASH_A))
    job = JobLeaseRepository(repository).enqueue(
        execution,
        attempt_id=attempt_id,
        payload={
            "attempt_input": AttemptInput.bind(
                scenario(
                    "scenario-one",
                    final_state_oracle={
                        "oracle_id": "state-one",
                        "kind": "predicate",
                        "expected": True,
                        "description": "fixture",
                    },
                ),
                envelope,
            ).model_dump(mode="json"),
            "harness": harness().model_dump(mode="json"),
        },
    )
    worker = DurableWorker(
        repository,
        registry,
        LocalArtifactStore(tmp_path / "artifacts"),
        state_oracle=FailingOracle(),
    )
    outcome = asyncio.run(worker.run_once("worker"))
    assert outcome and outcome.job_id == job and outcome.status == "completed"
    with repository.engine.connect() as conn:
        row = conn.execute(
            attempts.select().where(attempts.c.id == attempt_id)
        ).mappings().one()
    assert row["status"] == "completed"
    oracle_digest = row["result_metadata"]["state_oracle_artifact_digest"]
    assert oracle_digest
    assert json.loads(worker.artifact_store.get_bytes(oracle_digest))["evidence"] == {"oracle": "state-one"}


def test_zero_event_completed_result_is_incomplete_trace_evidence(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    outcome, row, _ = run_recorded_attempt(
        repository,
        tmp_path,
        completed_result(
            attempt_id="attempt-one",
            terminal_outcome="completed",
            completed_at=datetime.now(UTC) + timedelta(seconds=1),
            usage=ProviderUsage(
                evidence_source="fixture_recorded", total_tokens=1, context_tokens=1, tool_calls=0,
            ),
        ),
    )
    assert outcome and outcome.status == "failed"
    assert row["status"] == "incomplete"
    assert row["result_metadata"]["error_code"] == "partial_trace"
    assert row["result_metadata"]["trace_complete"] is False


def test_authoritative_oracle_cannot_upgrade_adapter_terminal_failure(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    outcome, row, _ = run_recorded_attempt(
        repository,
        tmp_path,
        ResultBundle(
            attempt_id="attempt-one", terminal_outcome="failed", completed_at=datetime.now(UTC) + timedelta(seconds=1),
            failure_classification="permanent_provider",
        ),
        events=(trace_event("attempt-one", "episode-one"),),
        state_oracle=UpgradingOracle(),
    )
    assert outcome and outcome.status == "completed"
    assert row["status"] == "failed"
    assert row["result_metadata"]["detail_code"] == "state_oracle"
    assert row["result_metadata"]["output_artifact_digest"] is None
    assert row["result_metadata"]["terminal_envelope"]["status"] == "failed"


def test_unknown_central_price_retains_completed_adapter_lifecycle(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    envelope = live_envelope(provider_model="gpt-4.1", provider="openai")
    claim_harness = HarnessSpec(
        harness_id="harness-one",
        version="1",
        adapter="recorded",
        adapter_identity="recorded-one",
        adapter_digest=HASH_A,
        timeout_seconds=5,
        configuration={},
        effective_configuration_hash=sha256({}),
        schema_hashes=HarnessSchemaHashes(
            input_hash=HASH_A, output_hash=HASH_A, trace_hash=HASH_A, config_schema_hash=HASH_A,
        ),
        claim_eligibility="protocol_only",
    )
    outcome, row, _ = run_recorded_attempt(
        repository,
        tmp_path,
        completed_result(
            attempt_id="attempt-one",
            terminal_outcome="completed",
            completed_at=datetime.now(UTC) + timedelta(seconds=1),
            usage=provider_usage(),
        ),
        events=(trace_event("attempt-one", "episode-one"),),
        envelope=envelope,
        claim_eligibility="protocol_only",
        harness_spec=claim_harness,
    )
    assert outcome and outcome.status == "completed"
    assert row["status"] == "completed"
    assert row["result_metadata"]["detail_code"] is None
    assert row["result_metadata"]["cost_status"] == "unknown"
    assert row["result_metadata"]["cost_usd"] is None
    assert "claim_eligible_completion_requires_central_price_resolution" in row["result_metadata"]["limitations"]
    assert row["result_metadata"]["terminal_envelope"]["status"] == "completed"
    assert row["result_metadata"]["terminal_envelope"]["response_hash"] == row["result_metadata"]["output_artifact_digest"]


def test_incomplete_result_with_bound_output_is_persisted_and_re_resolved(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    output = b'{"response":"observed"}'
    response_hash = sha256_bytes(output)
    outcome, row, store = run_recorded_attempt(
        repository,
        tmp_path,
        ResultBundle(
            attempt_id="attempt-one", terminal_outcome="incomplete",
            completed_at=datetime.now(UTC) + timedelta(seconds=1),
            failure_classification="permanent_protocol",
            response_hash=response_hash, response_artifact_id="response",
            artifacts=(ArtifactRef(
                artifact_id="response", media_type="application/json",
                sha256=response_hash, content=output,
            ),),
        ),
        events=(trace_event("attempt-one", "episode-one"),),
    )
    assert outcome and outcome.status == "completed"
    assert row["status"] == "incomplete"
    assert row["result_metadata"]["output_artifact_digest"] == response_hash
    assert row["result_metadata"]["terminal_envelope"]["response_hash"] == response_hash
    assert store.get_bytes(response_hash) == output


def test_captured_adapter_failure_queues_evaluation_before_execution_terminalization(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    outcome, row, _ = run_recorded_attempt(
        repository,
        tmp_path,
        ResultBundle(
            attempt_id="attempt-one", terminal_outcome="failed", completed_at=datetime.now(UTC) + timedelta(seconds=1),
            failure_classification="permanent_provider",
        ),
        events=(trace_event("attempt-one", "episode-one"),),
    )
    with repository.engine.connect() as conn:
        attempt_job = conn.execute(jobs.select().where(
            jobs.c.attempt_id == "attempt-one", jobs.c.kind == "attempt",
        )).mappings().one()
        evaluation_job = conn.execute(jobs.select().where(
            jobs.c.attempt_id == "attempt-one", jobs.c.kind == "evaluation",
        )).mappings().one()
        execution = conn.execute(executions.select().where(
            executions.c.id == attempt_job["execution_id"],
        )).mappings().one()
    assert outcome and outcome.status == "completed"
    assert row["status"] == "failed"
    assert attempt_job["status"] == "completed"
    assert evaluation_job["status"] == "queued"
    assert execution["status"] == "running"
    assert row["result_metadata"]["terminal_envelope"]["status"] == "failed"
    assert row["result_metadata"]["terminal_envelope"]["response_hash"] is None
    # The adapter worker can never steal the evaluator's follow-up lease.
    assert asyncio.run(DurableWorker(repository, AdapterRegistry(), LocalArtifactStore(tmp_path / "isolated")).run_once("worker")) is None
    with repository.engine.connect() as conn:
        assert conn.execute(jobs.select().where(jobs.c.id == evaluation_job["id"])).mappings().one()["status"] == "queued"


def test_missing_completed_output_artifact_is_worker_failure(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    outcome, row, _ = run_recorded_attempt(
        repository,
        tmp_path,
        ResultBundle.model_construct(
            attempt_id="attempt-one", terminal_outcome="completed", completed_at=datetime.now(UTC) + timedelta(seconds=1),
            response_hash=HASH_A, response_artifact_id="missing", artifacts=(),
            usage=ProviderUsage(
                evidence_source="fixture_recorded", total_tokens=1, context_tokens=1, tool_calls=0,
            ),
        ),
        events=(trace_event("attempt-one", "episode-one"),),
    )
    with repository.engine.connect() as conn:
        job = conn.execute(jobs.select().where(jobs.c.attempt_id == "attempt-one")).mappings().one()
        followups = conn.execute(jobs.select().where(
            jobs.c.attempt_id == "attempt-one", jobs.c.kind == "evaluation",
        )).mappings().all()
    assert outcome and outcome.status == "failed"
    assert row["status"] == "failed"
    assert job["status"] == "failed"
    assert followups == []
    assert row["result_metadata"]["error_code"] in {"ValueError", "output_artifact_evidence_missing"}


def test_terminal_event_is_unique_and_retry_requires_transient_classification(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0)
    attempt = repository.create_attempt(episode, 0, attempt_id="attempt-one")
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(execution, attempt_id=attempt, payload={})
    lease = leases.claim("worker", lease_seconds=10)
    assert lease
    assert (
        leases.fail(
            job,
            "worker",
            lease_token=lease.token,
            result_metadata={"failure_classification": "permanent_protocol"},
        )
        == "failed"
    )
    assert (
        leases.fail(
            job,
            "worker",
            lease_token=lease.token,
            result_metadata={"failure_classification": "permanent_protocol"},
        )
        == "failed"
    )
    with repository.engine.connect() as conn:
        events = conn.execute(
            attempt_events.select().where(
                attempt_events.c.attempt_id == attempt,
                attempt_events.c.event_type == "terminal",
            )
        ).all()
    assert len(events) == 1
    with pytest.raises(ValueError, match="transient"):
        leases.retry(job)


def test_retry_rebinds_attempt_input_and_executes_new_attempt(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        execution, 0, episode_id="episode-one", scenario_id="scenario-one"
    )
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    envelope = live_envelope(
        provider_model="recorded",
        provider="test",
        endpoint_id=None,
        pinned_endpoint_digest=None,
        budget=BudgetSpec(
            max_attempts=2,
            max_cost_usd=1,
            max_latency_seconds=5,
            max_tokens=5,
            max_tool_calls=0,
            max_context_tokens=2,
        ),
    )
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(
        execution,
        attempt_id="attempt-one",
        payload={
            "attempt_input": attempt_input(envelope).model_dump(mode="json"),
            "harness": harness().model_dump(mode="json"),
        },
    )
    claimed = leases.claim("first", lease_seconds=10)
    assert (
        claimed
        and leases.fail(
            job, "first", lease_token=claimed.token, result_metadata={"failure_classification": "transient"}
        )
        == "failed"
    )
    retry_attempt, retry_job = leases.retry(job)
    with repository.engine.connect() as conn:
        payload = (
            conn.execute(jobs.select().where(jobs.c.id == retry_job))
            .mappings()
            .one()["payload"]
        )
    assert payload["attempt_input"]["attempt"]["attempt_id"] == retry_attempt
    assert payload["attempt_input"]["attempt"]["request_hash"] != envelope.request_hash
    result = completed_result(
        attempt_id=retry_attempt,
        terminal_outcome="completed",
        completed_at=datetime.now(UTC) + timedelta(seconds=1),
        usage=ProviderUsage(
            evidence_source="fixture_recorded",
            total_tokens=1,
            context_tokens=1,
            tool_calls=0,
        ),
    )
    registry = AdapterRegistry()
    asyncio.run(
        registry.install_trusted(
            RecordedAdapter(
                adapter_id="recorded-one",
                adapter_digest=HASH_A,
                results={retry_attempt: result},
                events={retry_attempt: (trace_event(retry_attempt, episode),)},
            ),
            HASH_A,
        )
    )
    outcome = asyncio.run(
        DurableWorker(
            repository, registry, LocalArtifactStore(tmp_path / "retry")
        ).run_once("second")
    )
    assert outcome and outcome.job_id == retry_job and outcome.status == "completed"


def test_captured_transient_adapter_failure_retries_with_pending_evaluation_and_one_episode(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        execution, 0, episode_id="episode-one", scenario_id="scenario-one",
    )
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    envelope = live_envelope(
        provider_model="recorded", provider="test", endpoint_id=None,
        pinned_endpoint_digest=None,
        budget=BudgetSpec(
            max_attempts=2, max_cost_usd=1, max_latency_seconds=5,
            max_tokens=5, max_tool_calls=0, max_context_tokens=2,
        ),
    )
    failure = ResultBundle(
        attempt_id="attempt-one", terminal_outcome="failed",
        completed_at=datetime.now(UTC) + timedelta(seconds=1),
        failure_classification="transient_adapter",
    )
    first_registry = AdapterRegistry()
    asyncio.run(first_registry.install_trusted(RecordedAdapter(
        adapter_id="recorded-one", adapter_digest=HASH_A,
        results={"attempt-one": failure},
        events={"attempt-one": (trace_event("attempt-one", episode),)},
    ), HASH_A))
    leases = JobLeaseRepository(repository)
    first_job = leases.enqueue(
        execution, attempt_id="attempt-one", payload={
            "attempt_input": attempt_input(envelope).model_dump(mode="json"),
            "harness": harness().model_dump(mode="json"),
        },
    )
    first_worker = DurableWorker(repository, first_registry, LocalArtifactStore(tmp_path / "first"))
    first_outcome = asyncio.run(first_worker.run_once("first"))
    assert first_outcome and first_outcome.status == "completed"
    retry_attempt, retry_job = first_worker.retry(first_job)

    with repository.engine.connect() as conn:
        first_attempt_job = conn.execute(jobs.select().where(jobs.c.id == first_job)).mappings().one()
        prior_evaluation = conn.execute(jobs.select().where(
            jobs.c.attempt_id == "attempt-one", jobs.c.kind == "evaluation",
        )).mappings().one()
        retry_row = conn.execute(attempts.select().where(attempts.c.id == retry_attempt)).mappings().one()
        execution_row = conn.execute(executions.select().where(executions.c.id == execution)).mappings().one()
    assert first_attempt_job["status"] == "completed"
    assert prior_evaluation["status"] == "queued"
    assert retry_row["ordinal"] == 1
    assert retry_row["request_metadata"]["retry_of_attempt_id"] == "attempt-one"
    assert execution_row["status"] in {"queued", "running"}

    retry_result = completed_result(
        attempt_id=retry_attempt, terminal_outcome="completed",
        completed_at=datetime.now(UTC) + timedelta(seconds=2),
        usage=ProviderUsage(
            evidence_source="fixture_recorded", total_tokens=1,
            context_tokens=1, tool_calls=0,
        ),
    )
    retry_registry = AdapterRegistry()
    asyncio.run(retry_registry.install_trusted(RecordedAdapter(
        adapter_id="recorded-one", adapter_digest=HASH_A,
        results={retry_attempt: retry_result},
        events={retry_attempt: (trace_event(retry_attempt, episode),)},
    ), HASH_A))
    retry_outcome = asyncio.run(DurableWorker(
        repository, retry_registry, LocalArtifactStore(tmp_path / "retry"),
    ).run_once("retry"))
    assert retry_outcome and retry_outcome.job_id == retry_job and retry_outcome.status == "completed"
    with repository.engine.connect() as conn:
        evaluation_jobs = conn.execute(jobs.select().where(
            jobs.c.kind == "evaluation", jobs.c.execution_id == execution,
        )).mappings().all()
        episode_ids = conn.execute(attempts.select().with_only_columns(attempts.c.episode_id).where(
            attempts.c.episode_id == episode,
        )).scalars().all()
        execution_row = conn.execute(executions.select().where(executions.c.id == execution)).mappings().one()
    assert len(evaluation_jobs) == 2
    assert {row["status"] for row in evaluation_jobs} == {"queued"}
    assert set(episode_ids) == {episode}  # retries are one episode-level analysis denominator
    assert execution_row["status"] in {"queued", "running"}


@pytest.mark.parametrize(
    ("job_outcome", "attempt_status", "metadata"),
    [
        ("completed", "failed", {"captured_adapter_terminal": True, "failure_classification": "permanent_adapter"}),
        ("failed", "failed", {}),
        ("cancelled", "cancelled", {}),
        ("completed", "completed", {"captured_adapter_terminal": True}),
    ],
)
def test_retry_refuses_permanent_unclassified_cancelled_and_completed_attempts(
    repository: ArenaRepository,
    job_outcome: str,
    attempt_status: str,
    metadata: dict[str, object],
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0)
    attempt = repository.create_attempt(episode, 0)
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(execution, attempt_id=attempt, payload={})
    lease = leases.claim("worker", lease_seconds=10)
    assert lease
    assert leases.finalize(
        job, "worker", outcome=job_outcome, attempt_status=attempt_status,
        result_metadata=metadata, lease_token=lease.token,
    ) == job_outcome
    with pytest.raises(ValueError):
        leases.retry(job)


def test_retry_refuses_exhausted_attempt_budget(repository: ArenaRepository) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        execution, 0, episode_id="episode-one", scenario_id="scenario-one",
    )
    attempt = repository.create_attempt(episode, 0, attempt_id="attempt-one")
    envelope = live_envelope(
        provider_model="recorded", provider="test", endpoint_id=None,
        pinned_endpoint_digest=None,
        budget=BudgetSpec(
            max_attempts=1, max_cost_usd=1, max_latency_seconds=5,
            max_tokens=5, max_tool_calls=0, max_context_tokens=2,
        ),
    )
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(execution, attempt_id=attempt, payload={
        "attempt_input": attempt_input(envelope).model_dump(mode="json"),
        "harness": harness().model_dump(mode="json"),
    })
    lease = leases.claim("worker", lease_seconds=10)
    assert lease
    assert leases.fail(
        job, "worker", lease_token=lease.token, result_metadata={"failure_classification": "transient"},
    ) == "failed"
    with pytest.raises(ValueError, match="attempt budget"):
        leases.retry(job)


def test_enqueue_and_worker_reject_attempt_from_another_execution(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)
    source_execution = repository.create_execution("experiment-one")
    target_execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        source_execution, 0, episode_id="episode-one", scenario_id="scenario-one"
    )
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    envelope = live_envelope(
        provider_model="recorded",
        provider="test",
        endpoint_id=None,
        pinned_endpoint_digest=None,
    )
    payload = {
        "attempt_input": attempt_input(envelope).model_dump(mode="json"),
        "harness": harness().model_dump(mode="json"),
    }
    leases = JobLeaseRepository(repository)
    with pytest.raises(ValueError, match="belong"):
        leases.enqueue(target_execution, attempt_id="attempt-one", payload=payload)
    with repository.transaction() as conn:
        conn.execute(
            jobs.insert().values(
                id="cross-execution-job",
                execution_id=target_execution,
                attempt_id="attempt-one",
                kind="attempt",
                status="queued",
                attempt_count=0,
                available_at=datetime.now(UTC),
                payload=payload,
            )
        )
    outcome = asyncio.run(
        DurableWorker(
            repository,
            AdapterRegistry(),
            LocalArtifactStore(tmp_path / "cross-execution"),
        ).run_once("worker")
    )
    assert outcome and outcome.status == "failed"


def test_supervisor_heartbeats_and_cancels_live_adapter(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        execution, 0, episode_id="episode-one", scenario_id="scenario-one"
    )
    attempt_id = "attempt-one"
    repository.create_attempt(episode, 0, attempt_id=attempt_id)
    envelope = AttemptEnvelope(
        attempt_id=attempt_id,
        episode_id=episode,
        ordinal=1,
        provider_model="recorded",
        provider="test",
        harness_id="harness-one",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=1,
            max_cost_usd=1,
            max_latency_seconds=2,
            max_tokens=10,
            max_tool_calls=0,
            max_context_tokens=10,
        ),
        provenance=provenance(),
        request_hash=HASH_A,
        status="queued",
        queued_at=NOW,
    )
    result = completed_result(
        attempt_id=attempt_id,
        terminal_outcome="completed",
        completed_at=datetime.now(UTC) + timedelta(seconds=1),
        usage=ProviderUsage(
            evidence_source="fixture_recorded",
            total_tokens=1,
            context_tokens=1,
            tool_calls=0,
        ),
    )
    adapter = SlowRecordedAdapter(
        adapter_id="recorded-one", adapter_digest=HASH_A, results={attempt_id: result}
    )
    registry = AdapterRegistry()
    asyncio.run(registry.install_trusted(adapter, HASH_A))
    leases = JobLeaseRepository(repository)
    job = leases.enqueue(
        execution,
        attempt_id=attempt_id,
        payload={
            "attempt_input": attempt_input(envelope).model_dump(mode="json"),
            "harness": harness()
            .model_copy(update={"timeout_seconds": 2})
            .model_dump(mode="json"),
        },
    )
    worker = DurableWorker(
        repository, registry, LocalArtifactStore(tmp_path / "artifacts")
    )

    async def exercise() -> None:
        task = asyncio.create_task(worker.run_once("worker", lease_seconds=0.3))
        await asyncio.sleep(0.15)
        assert leases.reclaim_expired() == 0
        assert leases.request_cancel(job)
        outcome = await task
        assert outcome and outcome.status == "cancelled"

    asyncio.run(exercise())
    assert attempt_id in adapter._cancelled


def test_late_trace_is_drained_before_completed(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        execution, 0, episode_id="episode-one", scenario_id="scenario-one"
    )
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    envelope = AttemptEnvelope(
        attempt_id="attempt-one",
        episode_id=episode,
        ordinal=1,
        provider_model="recorded",
        provider="test",
        harness_id="harness-one",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=1,
            max_cost_usd=1,
            max_latency_seconds=1,
            max_tokens=10,
            max_tool_calls=0,
            max_context_tokens=10,
        ),
        provenance=provenance(),
        request_hash=HASH_A,
        status="queued",
        queued_at=NOW,
    )
    result = completed_result(
        attempt_id="attempt-one",
        terminal_outcome="completed",
        completed_at=datetime.now(UTC) + timedelta(seconds=1),
        usage=ProviderUsage(
            evidence_source="fixture_recorded",
            total_tokens=1,
            context_tokens=1,
            tool_calls=0,
        ),
    )
    adapter = DelayedTraceRecordedAdapter(
        adapter_id="recorded-one",
        adapter_digest=HASH_A,
        results={"attempt-one": result},
    )
    registry = AdapterRegistry()
    asyncio.run(registry.install_trusted(adapter, HASH_A))
    JobLeaseRepository(repository).enqueue(
        execution,
        attempt_id="attempt-one",
        payload={
            "attempt_input": attempt_input(envelope).model_dump(mode="json"),
            "harness": harness()
            .model_copy(update={"timeout_seconds": 1})
            .model_dump(mode="json"),
        },
    )
    store = LocalArtifactStore(tmp_path / "artifacts")
    outcome = asyncio.run(DurableWorker(repository, registry, store).run_once("worker"))
    assert outcome and outcome.status == "completed"
    with repository.engine.connect() as conn:
        assert conn.execute(
            attempt_events.select().where(
                attempt_events.c.attempt_id == "attempt-one",
                attempt_events.c.event_type == "trace",
            )
        ).mappings().one()["payload"]["payload"] == {"late": True}
        metadata = conn.execute(
            attempts.select().where(attempts.c.id == "attempt-one")
        ).mappings().one()["result_metadata"]
    assert metadata["input_artifact_digest"]
    assert metadata["output_artifact_digest"] == result.response_hash
    assert metadata["trace_complete"] is True
    assert canonical_json(json.loads(store.get_bytes(metadata["trace_artifact_digest"]))) == canonical_json([
        TraceEvent(
            trace_id="trace-one",
            episode_id="episode-one",
            attempt_id="attempt-one",
            sequence=0,
            actor="model",
            event_type="response",
            timestamp=NOW,
            monotonic_time=0,
            payload={"late": True},
            payload_hash=HASH_A,
        ).model_dump(mode="json")
    ])
    persisted_input = json.loads(store.get_bytes(metadata["input_artifact_digest"]))
    assert persisted_input["attempt"]["status"] == "started"
    assert persisted_input["attempt"]["attempt_id"] == "attempt-one"
    assert metadata["terminal_envelope"]["status"] == "completed"
    assert metadata["terminal_envelope"]["response_hash"] == result.response_hash


@pytest.mark.parametrize(
    ("adapter_type", "expected_status", "expected_attempt_status", "expected_cancel"),
    [
        (NonterminatingTraceRecordedAdapter, "failed", "incomplete", False),
        (TimeoutRecordedAdapter, "failed", "timed_out", True),
    ],
)
def test_incomplete_trace_and_timeout_never_complete(
    repository: ArenaRepository,
    tmp_path: Path,
    adapter_type,
    expected_status: str,
    expected_attempt_status: str,
    expected_cancel: bool,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(
        execution, 0, episode_id="episode-one", scenario_id="scenario-one"
    )
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    envelope = AttemptEnvelope(
        attempt_id="attempt-one",
        episode_id=episode,
        ordinal=1,
        provider_model="recorded",
        provider="test",
        harness_id="harness-one",
        factor_assignments={},
        budget=BudgetSpec(
            max_attempts=1,
            max_cost_usd=1,
            max_latency_seconds=1,
            max_tokens=10,
            max_tool_calls=0,
            max_context_tokens=10,
        ),
        provenance=provenance(),
        request_hash=HASH_A,
        status="queued",
        queued_at=NOW,
    )
    result = completed_result(
        attempt_id="attempt-one",
        terminal_outcome="completed",
        completed_at=datetime.now(UTC) + timedelta(seconds=1),
        usage=ProviderUsage(
            evidence_source="fixture_recorded",
            total_tokens=1,
            context_tokens=1,
            tool_calls=0,
        ),
    )
    adapter = adapter_type(
        adapter_id="recorded-one",
        adapter_digest=HASH_A,
        results={"attempt-one": result},
    )
    registry = AdapterRegistry()
    asyncio.run(registry.install_trusted(adapter, HASH_A))
    JobLeaseRepository(repository).enqueue(
        execution,
        attempt_id="attempt-one",
        payload={
            "attempt_input": attempt_input(envelope).model_dump(mode="json"),
            "harness": harness()
            .model_copy(update={"timeout_seconds": 1})
            .model_dump(mode="json"),
        },
    )
    outcome = asyncio.run(
        DurableWorker(
            repository, registry, LocalArtifactStore(tmp_path / "artifacts")
        ).run_once("worker")
    )
    assert outcome and outcome.status == expected_status
    assert ("attempt-one" in adapter._cancelled) is expected_cancel
    with repository.engine.connect() as conn:
        row = conn.execute(attempts.select().where(attempts.c.id == "attempt-one")).mappings().one()
    assert row["status"] == expected_attempt_status
    assert row["result_metadata"]["trace_complete"] is False
    if adapter_type is NonterminatingTraceRecordedAdapter:
        digest = row["result_metadata"]["trace_artifact_digest"]
        assert digest
        assert json.loads(LocalArtifactStore(tmp_path / "artifacts").get_bytes(digest))[0]["payload"] == {"partial": True}


def test_live_usage_evidence_requires_all_observations_and_enforces_budgets() -> None:
    envelope = live_envelope()
    DurableWorker._enforce_usage(
        completed_result(
            attempt_id="attempt-one",
            terminal_outcome="completed",
            completed_at=NOW,
            usage=provider_usage(),
        ),
        envelope,
        claim_eligibility="protocol_only",
    )
    with pytest.raises(MissingUsageEvidence):
        DurableWorker._enforce_usage(
            completed_result(
                attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW
            ),
            envelope,
            claim_eligibility="protocol_only",
        )
    for usage in (
        provider_usage(total_tokens=6, input_tokens=2, output_tokens=4),
        provider_usage(context_tokens=3),
        provider_usage(tool_calls=1),
        provider_usage(observed_endpoint_digest=HASH_B),
    ):
        with pytest.raises((MissingUsageEvidence, UsageMismatch)):
            DurableWorker._enforce_usage(
                completed_result(
                    attempt_id="attempt-one",
                    terminal_outcome="completed",
                    completed_at=NOW,
                    usage=usage,
                ),
                envelope,
                claim_eligibility="protocol_only",
            )


class QuoteResolver:
    def __init__(self, quote: PriceQuote | None) -> None:
        self.quote = quote

    def resolve(
        self, *, provider: str, model_id: str, usage: ProviderUsage
    ) -> PriceQuote | None:
        return self.quote


def test_central_price_resolver_reconciles_only_matching_quote(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0, episode_id="episode-one")
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    usage = provider_usage(actual_cost_usd=0.01)
    result = completed_result(
        attempt_id="attempt-one",
        terminal_outcome="completed",
        completed_at=NOW,
        usage=usage,
    )
    registry = AdapterRegistry()
    worker = DurableWorker(
        repository,
        registry,
        LocalArtifactStore(tmp_path / "artifacts"),
        price_resolver=QuoteResolver(
            PriceQuote("openai", "gpt-4.1", "central-r1", HASH_A, 0.01)
        ),
    )
    ledger = worker.budgets.reserve(
        execution, "attempt-one", model_id="gpt-4.1", max_cost_usd=1
    )
    assert worker._reconcile(ledger, result, live_envelope()).status == "reconciled"
    ledger = worker.budgets.reserve(
        execution, "attempt-one", model_id="gpt-4.1", max_cost_usd=1
    )
    worker.price_resolver = QuoteResolver(
        PriceQuote("openai", "gpt-4.1", "central-r1", HASH_B, 0.01)
    )
    assert worker._reconcile(ledger, result, live_envelope()).status == "mismatch"
    ledger = worker.budgets.reserve(
        execution, "attempt-one", model_id="gpt-4.1", max_cost_usd=1
    )
    worker.price_resolver = None
    assert worker._reconcile(ledger, result, live_envelope()).status == "unknown"


def test_aggregate_reservation_gate_is_atomic_for_cost_and_attempt_count(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0)
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    service = BudgetReservationService(repository)
    service.reserve_with_aggregate(
        execution,
        "attempt-one",
        model_id="gpt-4.1",
        max_cost_usd=0.5,
        max_attempts=1,
        max_total_cost_usd=1,
    )
    with pytest.raises(ValueError, match="aggregate attempt"):
        service.reserve_with_aggregate(
            execution,
            "attempt-two",
            model_id="gpt-4.1",
            max_cost_usd=0.5,
            max_attempts=1,
            max_total_cost_usd=1,
        )


def test_aggregate_reservation_gates_and_reconciliation_persist_observed_usage(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0)
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    service = BudgetReservationService(repository)
    service.reserve_with_aggregate(
        execution,
        "attempt-one",
        model_id="gpt-4.1",
        max_cost_usd=0.5,
        max_attempts=2,
        max_total_cost_usd=1,
        max_tokens=8,
        max_tool_calls=2,
        max_total_tokens=10,
        max_total_tool_calls=2,
    )
    with pytest.raises(ValueError, match="token reservation"):
        service.reserve_with_aggregate(
            execution,
            "attempt-two",
            model_id="gpt-4.1",
            max_cost_usd=0.5,
            max_attempts=2,
            max_total_cost_usd=1,
            max_tokens=3,
            max_tool_calls=0,
            max_total_tokens=10,
            max_total_tool_calls=2,
        )
    ledger = service.latest_for_attempt("attempt-one")
    assert (
        ledger and ledger["reserved_max_tokens"] == 8 and ledger["total_tokens"] is None
    )
    observed = provider_usage(
        input_tokens=2, output_tokens=3, total_tokens=5, context_tokens=2, tool_calls=1
    )
    assert service.unknown(str(ledger["id"]), usage=observed).status == "unknown"
    persisted = service.latest_for_attempt("attempt-one")
    assert (
        persisted and persisted["input_tokens"] == 2 and persisted["output_tokens"] == 3
    )
    assert (
        persisted["total_tokens"] == 5
        and persisted["context_tokens"] == 2
        and persisted["tool_calls"] == 1
    )


def test_central_catalogue_resolver_refuses_unrepresented_billing_dimensions() -> None:
    resolver = CentralPriceResolver()
    standard = resolver.resolve(
        provider="openai", model_id="gpt-4.1", usage=provider_usage()
    )
    assert (
        standard
        and standard.price_catalog_revision == "2026-08-14"
        and standard.cost_usd == pytest.approx(0.000028)
    )
    replay_usage = provider_usage(
        input_tokens=50_000, output_tokens=0, total_tokens=50_000
    )
    replay_quote = resolver.resolve(
        provider="openai", model_id="gpt-4.1", usage=replay_usage
    )
    assert replay_quote and replay_quote.cost_usd == 0.1
    assert replay_quote == resolver.resolve(
        provider="openai", model_id="gpt-4.1", usage=replay_usage
    )
    assert (
        resolver.resolve(
            provider="openrouter", model_id="gpt-4.1", usage=provider_usage()
        )
        is None
    )
    assert (
        resolver.resolve(
            provider="openai",
            model_id="gpt-4.1",
            usage=provider_usage(cached_input_tokens=1),
        )
        is None
    )
    assert (
        resolver.resolve(
            provider="openai",
            model_id="gpt-4.1",
            usage=provider_usage(service_tier="priority"),
        )
        is None
    )
    long_context = resolver.resolve(
        provider="gemini",
        model_id="gemini-2.5-pro",
        usage=provider_usage(context_tokens=200_001, billing_profile="long_context"),
    )
    assert long_context and long_context.cost_usd == pytest.approx(0.00005)
    assert (
        resolver.resolve(
            provider="gemini",
            model_id="gemini-2.5-pro",
            usage=provider_usage(context_tokens=200_001),
        )
        is None
    )


def test_currency_reconciliation_quantizes_binary_float_artifacts_and_replays_exactly(
    repository: ArenaRepository,
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0)
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    service = BudgetReservationService(repository)
    ledger = service.reserve(
        execution, "attempt-one", model_id="gpt-4.1", max_cost_usd=0.3
    )
    observed = provider_usage(actual_cost_usd=0.1 + 0.2)
    result = service.reconcile(
        ledger,
        input_tokens=2,
        output_tokens=3,
        actual_cost_usd=observed.actual_cost_usd,
        provider_usage_digest=HASH_A,
        price_catalog_revision="2026-08-14",
        expected_cost_usd=0.3,
        usage=observed,
    )
    assert result.status == "reconciled" and result.cost_usd == 0.3
    assert currency(0.1 + 0.2) == currency(0.3)
    persisted = service.latest_for_attempt("attempt-one")
    assert (
        persisted
        and persisted["cost_usd"] == 0.3
        and persisted["actual_cost_usd"] == 0.3
    )


def test_currency_budget_boundary_rejects_amount_beyond_quantization_tolerance(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)
    execution = repository.create_execution("experiment-one")
    episode = repository.create_episode(execution, 0)
    repository.create_attempt(episode, 0, attempt_id="attempt-one")
    usage = provider_usage(actual_cost_usd=0.3000000006)
    worker = DurableWorker(
        repository,
        AdapterRegistry(),
        LocalArtifactStore(tmp_path / "artifacts"),
        price_resolver=QuoteResolver(
            PriceQuote("openai", "gpt-4.1", "2026-08-14", HASH_A, 0.3000000006)
        ),
    )
    ledger = worker.budgets.reserve(
        execution, "attempt-one", model_id="gpt-4.1", max_cost_usd=0.3
    )
    envelope = live_envelope(
        budget=BudgetSpec(
            max_attempts=1,
            max_cost_usd=0.3,
            max_latency_seconds=5,
            max_tokens=5,
            max_tool_calls=0,
            max_context_tokens=2,
        )
    )
    assert (
        worker._reconcile(
            ledger,
            completed_result(
                attempt_id="attempt-one",
                terminal_outcome="completed",
                completed_at=NOW,
                usage=usage,
            ),
            envelope,
        ).status
        == "mismatch"
    )


def test_result_lifecycle_rejects_early_completion_and_hash_or_attempt_substitution() -> (
    None
):
    envelope = live_envelope().model_copy(
        update={"status": "started", "started_at": NOW}
    )
    with pytest.raises(ValueError, match="precedes"):
        DurableWorker._validate_result_lifecycle(
            completed_result(
                attempt_id="attempt-one",
                terminal_outcome="completed",
                completed_at=NOW - timedelta(seconds=1),
            ),
            envelope,
        )
    with pytest.raises(ValueError, match="attempt_id"):
        DurableWorker._validate_result_lifecycle(
            completed_result(
                attempt_id="attempt-two",
                terminal_outcome="completed",
                completed_at=NOW + timedelta(seconds=1),
            ),
            envelope,
        )
    bound = envelope.model_copy(update={"response_hash": HASH_A})
    with pytest.raises(ValueError, match="response_hash"):
        DurableWorker._validate_result_lifecycle(
            completed_result(
                attempt_id="attempt-one",
                terminal_outcome="completed",
                completed_at=NOW + timedelta(seconds=1),
            ),
            bound,
        )


def test_completed_result_fails_closed_for_missing_or_mismatched_output_artifact(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    worker = DurableWorker(repository, AdapterRegistry(), store)
    response = ArtifactRef(
        artifact_id="response",
        media_type="application/json",
        sha256=sha256_bytes(b"actual"),
        content=b"actual",
    )
    _, artifact_ids = worker._persist_artifacts((response,))
    missing = ResultBundle.model_construct(
        attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
        response_hash=response.sha256, response_artifact_id="missing", artifacts=(),
    )
    mismatched = ResultBundle.model_construct(
        attempt_id="attempt-one", terminal_outcome="completed", completed_at=NOW,
        response_hash=HASH_A, response_artifact_id="response", artifacts=(response,),
    )
    with pytest.raises(MissingOutputEvidence):
        worker._resolve_output_artifact(missing, artifact_ids)
    with pytest.raises(MissingOutputEvidence):
        worker._resolve_output_artifact(mismatched, artifact_ids)


def test_manipulation_evidence_requires_exact_bound_factor_fidelity(
    repository: ArenaRepository, tmp_path: Path,
) -> None:
    worker = DurableWorker(repository, AdapterRegistry(), LocalArtifactStore(tmp_path / "artifacts"))
    envelope = live_envelope().model_copy(update={"factor_assignments": {"guard": True}})

    def fidelity(sequence: int, factor_id: str = "guard") -> TraceEvent:
        return TraceEvent(
            trace_id=f"trace-{sequence}", episode_id="episode-one", attempt_id="attempt-one",
            sequence=sequence, actor="harness", event_type="state", timestamp=NOW,
            monotonic_time=sequence, payload={
                "event": "factor_fidelity", "factor_id": factor_id,
                "passed": True, "compute_context_matched": True,
            }, payload_hash=HASH_A,
        )

    passed, digest, detail = worker._derive_manipulation_evidence(envelope, [fidelity(0)])
    assert passed and detail is None
    assert json.loads(worker.artifact_store.get_bytes(digest))["fidelity"][0]["payload"]["factor_id"] == "guard"
    passed, _, detail = worker._derive_manipulation_evidence(envelope, [fidelity(0), fidelity(1)])
    assert not passed and detail == "factor_fidelity_duplicate_or_ambiguous"
    passed, _, detail = worker._derive_manipulation_evidence(envelope, [fidelity(0, "other")])
    assert not passed and detail == "factor_fidelity_keys_do_not_match_bound_factor_assignments"


def test_fixture_completed_result_without_budget_usage_is_hold() -> None:
    with pytest.raises(MissingUsageEvidence):
        DurableWorker._enforce_usage(
                completed_result(
                attempt_id="attempt-one",
                terminal_outcome="completed",
                completed_at=NOW,
                usage=ProviderUsage(evidence_source="fixture_recorded", total_tokens=1),
            ),
            live_envelope(),
            claim_eligibility="fixture_only",
        )
    DurableWorker._enforce_usage(
        completed_result(
            attempt_id="attempt-one",
            terminal_outcome="completed",
            completed_at=NOW,
            usage=ProviderUsage(
                evidence_source="fixture_recorded",
                total_tokens=1,
                context_tokens=1,
                tool_calls=0,
            ),
        ),
        live_envelope(),
        claim_eligibility="fixture_only",
    )


def test_http_and_command_result_events_are_persisted_by_worker(
    repository: ArenaRepository, tmp_path: Path
) -> None:
    prepare_frozen(repository)

    def run(
        adapter,
        harness_spec: HarnessSpec,
        payload: dict[str, object],
        attempt_id: str,
        episode_id: str,
    ) -> None:
        execution = repository.create_execution("experiment-one")
        repository.create_episode(
            execution, 0, episode_id=episode_id, scenario_id="scenario-one"
        )
        repository.create_attempt(episode_id, 0, attempt_id=attempt_id)
        envelope = AttemptEnvelope(
            attempt_id=attempt_id,
            episode_id=episode_id,
            ordinal=1,
            provider_model="recorded",
            provider="test",
            harness_id="harness-one",
            factor_assignments={},
            budget=BudgetSpec(
                max_attempts=1,
                max_cost_usd=1,
                max_latency_seconds=2,
                max_tokens=10,
                max_tool_calls=0,
                max_context_tokens=10,
            ),
            provenance=provenance(),
            request_hash=HASH_A,
            status="queued",
            queued_at=NOW,
        )
        registry = AdapterRegistry()
        asyncio.run(
            registry.install_trusted(adapter, adapter._capabilities.adapter_digest)
        )
        JobLeaseRepository(repository).enqueue(
            execution,
            attempt_id=attempt_id,
            payload={
                "attempt_input": attempt_input(envelope).model_dump(mode="json"),
                "harness": harness_spec.model_dump(mode="json"),
                **payload,
            },
        )
        outcome = asyncio.run(
            DurableWorker(
                repository, registry, LocalArtifactStore(tmp_path / attempt_id)
            ).run_once("worker")
        )
        assert outcome and outcome.status == "completed"
        with repository.engine.connect() as conn:
            assert conn.execute(
                attempt_events.select().where(
                    attempt_events.c.attempt_id == attempt_id,
                    attempt_events.c.event_type == "trace",
                )
            ).one()

    def result(attempt_id: str) -> ResultBundle:
        return completed_result(
            attempt_id=attempt_id,
            terminal_outcome="completed",
            completed_at=datetime.now(UTC) + timedelta(seconds=1),
            usage=ProviderUsage(
                evidence_source="fixture_recorded",
                total_tokens=1,
                context_tokens=1,
                tool_calls=0,
            ),
        )

    http_event = TraceEvent(
        trace_id="trace-http",
        episode_id="episode-http",
        attempt_id="attempt-http",
        sequence=0,
        actor="model",
        event_type="response",
        timestamp=NOW,
        monotonic_time=0,
        payload={"transport": "http"},
        payload_hash=HASH_A,
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "events": [http_event.model_dump(mode="json")],
                    "result": result("attempt-http").model_dump(mode="json"),
                },
            )
        )
    )
    http_adapter = HttpRpcAdapter(
        adapter_id="http-one",
        adapter_digest=HASH_A,
        endpoint="http://127.0.0.1:9000/rpc",
        allowed_hosts=frozenset({"127.0.0.1"}),
        client=client,
    )
    run(
        http_adapter,
        HarnessSpec(
            harness_id="harness-one",
            version="1",
            adapter="http",
            adapter_identity="http-one",
            adapter_digest=HASH_A,
            timeout_seconds=2,
            execution_mode="remote",
            isolation="remote_sandbox",
        ),
        {},
        "attempt-http",
        "episode-http",
    )
    asyncio.run(client.aclose())

    command_event = TraceEvent(
        trace_id="trace-command",
        episode_id="episode-command",
        attempt_id="attempt-command",
        sequence=0,
        actor="model",
        event_type="response",
        timestamp=NOW,
        monotonic_time=0,
        payload={"transport": "command"},
        payload_hash=HASH_A,
    )
    executable = tmp_path / "event-runner"
    lines = "\n".join(
        (
            json.dumps({"event": command_event.model_dump(mode="json")}),
            json.dumps({"result": result("attempt-command").model_dump(mode="json")}),
        )
    )
    executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{lines}'\n", encoding="utf-8")
    executable.chmod(0o755)
    command_adapter = CommandJsonlAdapter(
        adapter_id="command-one",
        adapter_digest=HASH_A,
        executable=executable,
        executable_digest=sha256_bytes(executable.read_bytes()),
    )
    command_config = {"argv": [str(executable)]}
    run(
        command_adapter,
        HarnessSpec(
            harness_id="harness-one",
            version="1",
            adapter="cli",
            adapter_identity="command-one",
            adapter_digest=HASH_A,
            timeout_seconds=2,
            configuration=command_config,
            effective_configuration_hash=sha256(command_config),
        ),
        {},
        "attempt-command",
        "episode-command",
    )
