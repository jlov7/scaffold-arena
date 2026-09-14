from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select

from adapters_v1 import AttemptInput
from execution_v1 import ExecutionProvenance, ExperimentController
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import executions, jobs
from protocol_v1.models import (
    AggregateBudgetSpec,
    BudgetSpec,
    ExperimentSpec,
    HarnessSpec,
    SamplingSpec,
    ScenarioSpec,
)
from protocol_v1.study_pack import freeze_experiment

HASH = "a" * 64
NOW = datetime.now(UTC)


def _provenance() -> ExecutionProvenance:
    return ExecutionProvenance(
        code_revision="fixture",
        code_hash=HASH,
        runtime_image="fixture-runtime@sha256:abc",
        runtime_image_hash=HASH,
        environment_hash=HASH,
        prompt_hash=HASH,
        context_hash=HASH,
        tool_hash=HASH,
        source_refs=(
            {"source_uri": "synthetic://source", "content_hash": HASH},
        ),
        captured_at=NOW,
    )


def _scenario() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario-one",
        title="Scenario",
        task_family="fixture",
        prompt="Synthetic fixture prompt.",
    )


def _harness() -> HarnessSpec:
    return HarnessSpec(
        harness_id="harness-one",
        version="1",
        adapter="recorded",
        adapter_identity="recorded-one",
        adapter_digest=HASH,
        timeout_seconds=19,
    )


def _frozen_spec() -> ExperimentSpec:
    return freeze_experiment(
        ExperimentSpec(
            experiment_id="experiment-one",
            study_pack_id="pack-one",
            scenario_ids=("scenario-one",),
            harness_ids=("harness-one",),
            model_endpoints=(
                {
                    "endpoint_id": "endpoint-one",
                    "provider": "fixture-provider",
                    "model": "fixture-model",
                    "endpoint_digest": HASH,
                },
            ),
            sampling=SamplingSpec(
                temperature=0.35,
                top_p=0.82,
                max_tokens=256,
            ),
            repetitions=1,
            randomization_seed=77,
            deterministic_weight=0.7,
            budgets=BudgetSpec(
                max_attempts=3,
                max_cost_usd=1.0,
                max_latency_seconds=23.0,
                max_tokens=512,
                max_tool_calls=5,
                max_context_tokens=8192,
            ),
            aggregate_budget=AggregateBudgetSpec(
                max_total_cost_usd=2.0,
                max_total_tokens=1024,
                max_total_tool_calls=10,
                max_wall_time_seconds=60.0,
                max_attempts=4,
            ),
            owner_approval="approved",
        ),
        HASH,
    )


def _repository(tmp_path) -> ArenaRepository:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Test", project_id="project-one")
    repository.register_artifact(HASH, size_bytes=1, storage_uri="local://pack")
    pack_id = repository.create_study_pack_version(
        "project-one",
        "pack",
        "1.0.0",
        HASH,
        study_pack_id="pack-one",
    )
    frozen = _frozen_spec().model_dump(mode="json")
    unfrozen = {
        **frozen,
        "frozen": False,
        "freeze_hash": None,
        "frozen_at": None,
    }
    repository.create_experiment(
        "project-one",
        pack_id,
        "experiment",
        owner_approval="approved",
        experiment_id="experiment-one",
        definition=unfrozen,
    )
    repository.freeze_experiment(
        "experiment-one",
        expected_definition=unfrozen,
        frozen_definition=frozen,
        spec_hash=str(frozen["freeze_hash"]),
        study_pack_hash=HASH,
    )
    return repository


def _queued_payload(repository: ArenaRepository, job_id: str) -> dict:
    with repository.engine.connect() as connection:
        return dict(
            connection.execute(
                select(jobs.c.payload).where(jobs.c.id == job_id)
            ).scalar_one()
        )


def _queued_input(repository: ArenaRepository, job_id: str) -> AttemptInput:
    payload = _queued_payload(repository, job_id)
    return AttemptInput.model_validate_json(json.dumps(payload["attempt_input"]))


def test_controller_compiles_frozen_sampling_seed_and_limits_into_attempt_input(
    tmp_path,
) -> None:
    repository = _repository(tmp_path)
    controller = ExperimentController(
        repository,
        harnesses={"harness-one": _harness()},
        scenario_specs={"scenario-one": _scenario()},
    )

    first = controller.create_execution(
        "project-one",
        _frozen_spec(),
        request_key="first",
        provenance=_provenance(),
    )
    second = controller.create_execution(
        "project-one",
        _frozen_spec(),
        request_key="second",
        provenance=_provenance(),
    )

    first_input = _queued_input(repository, first.job_ids[0])
    second_input = _queued_input(repository, second.job_ids[0])
    controls = first_input.execution_controls

    assert controls.source == "frozen_experiment"
    assert controls.temperature == 0.35
    assert controls.top_p == 0.82
    assert controls.max_output_tokens == 256
    assert controls.timeout_seconds == 19.0
    assert controls.max_tool_calls == 5
    assert controls.max_context_tokens == 8192
    assert controls.max_attempts == 3
    assert controls.seed == second_input.execution_controls.seed
    assert controls.seed >= 0
    assert first_input.binding_digest != second_input.binding_digest


def test_controller_freezes_one_aggregate_wall_time_deadline_for_every_job(
    tmp_path,
) -> None:
    repository = _repository(tmp_path)
    controller = ExperimentController(
        repository,
        harnesses={"harness-one": _harness()},
        scenario_specs={"scenario-one": _scenario()},
    )

    created = controller.create_execution(
        "project-one",
        _frozen_spec(),
        request_key="deadline",
        provenance=_provenance(),
    )

    payload = _queued_payload(repository, created.job_ids[0])
    aggregate = payload["aggregate_budget"]
    with repository.engine.connect() as connection:
        parameters = dict(
            connection.execute(
                select(executions.c.parameters).where(
                    executions.c.id == created.execution_id
                )
            ).scalar_one()
        )

    assert aggregate["max_wall_time_seconds"] == 60.0
    assert aggregate["deadline_at"] == parameters["aggregate_deadline_at"]
    deadline = datetime.fromisoformat(aggregate["deadline_at"])
    created_at = datetime.fromisoformat(parameters["aggregate_started_at"])
    assert (deadline - created_at).total_seconds() == _frozen_spec().aggregate_budget.max_wall_time_seconds
