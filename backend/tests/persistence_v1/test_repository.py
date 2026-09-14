from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from persistence_v1 import (
    ArenaRepository,
    FrozenExperimentError,
    ImmutableVersionConflict,
    create_persistence_engine,
)
from persistence_v1.schema import (
    artifacts,
    attempt_events,
    attempts,
    episodes,
    experiments,
    metadata,
    projects,
    usage_ledger,
)
from protocol_v1 import ExperimentSpec
from protocol_v1 import freeze_experiment as freeze_protocol_experiment


@pytest.fixture
def repository(tmp_path: Path) -> ArenaRepository:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    return ArenaRepository(engine)


def _frozen_attempt(repository: ArenaRepository) -> tuple[str, str, str]:
    project = repository.create_project("Test", project_id="project")
    repository.register_artifact("a" * 64, size_bytes=1, storage_uri="local://a")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", "a" * 64)
    experiment = repository.create_experiment(project, pack, "experiment", owner_approval="approved", experiment_id="experiment-one")
    definition, spec_hash = _frozen_definition(experiment, "a" * 64)
    repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash="a" * 64)
    execution = repository.create_execution(experiment)
    episode = repository.create_episode(execution, 0)
    return project, repository.create_attempt(episode, 0), experiment


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


def test_register_artifact_is_atomic_for_identical_concurrent_content(
    repository: ArenaRepository,
) -> None:
    digest = "f" * 64
    barrier = Barrier(2)

    def register() -> None:
        barrier.wait()
        repository.register_artifact(
            digest,
            size_bytes=7,
            storage_uri="test://same-artifact",
            media_type="application/test",
            content_metadata={"source": "fixture"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: register(), range(2)))

    with repository.engine.connect() as conn:
        rows = conn.execute(select(artifacts).where(artifacts.c.digest == digest)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["media_type"] == "application/test"
    assert rows[0]["metadata_json"] == {"source": "fixture"}
    # Artifact role and media metadata describe each use, not the hashed bytes.
    # The same content may legitimately appear in several durable roles.
    repository.register_artifact(
        digest,
        size_bytes=7,
        storage_uri="test://same-artifact",
        media_type="application/vnd.scaffold-arena.trace+json",
        content_metadata={"artifact_role": "trace", "attempt_id": "attempt-two"},
    )
    with pytest.raises(ImmutableVersionConflict, match="different content location or size"):
        repository.register_artifact(
            digest,
            size_bytes=8,
            storage_uri="test://same-artifact",
            media_type="application/test",
            content_metadata={"source": "fixture"},
        )


def test_sqlite_repository_contract_and_frozen_experiment(repository: ArenaRepository) -> None:
    project, attempt, experiment = _frozen_attempt(repository)
    assert project == "project"
    assert repository.append_attempt_event(attempt, "started", {"source": "test"}) == 1
    assert repository.list_attempt_events(attempt)[0]["payload"] == {"source": "test"}
    with pytest.raises(FrozenExperimentError):
        repository.update_experiment_definition(experiment, {})
    with pytest.raises(FrozenExperimentError):
        repository.set_experiment_owner_approval(experiment, "rejected")
    with pytest.raises(IntegrityError, match="frozen experiments are immutable"), repository.transaction() as conn:
        conn.execute(experiments.update().where(experiments.c.id == experiment).values(name="tampered"))
    with repository.engine.connect() as conn:
        frozen = conn.execute(select(experiments.c.protocol_version, experiments.c.definition, experiments.c.spec_hash, experiments.c.study_pack_hash, experiments.c.owner_approval, experiments.c.frozen_at).where(experiments.c.id == experiment)).one()
    assert frozen[0] == "1.0"
    persisted = ExperimentSpec.model_validate_json(json.dumps(frozen[1]))
    assert persisted.frozen is True
    assert persisted.freeze_hash == frozen[2]
    assert persisted.study_pack_hash == frozen[3] == "a" * 64
    assert frozen[4] == "approved"
    assert frozen[5].replace(tzinfo=UTC) == datetime.fromisoformat(str(frozen[1]["frozen_at"])).astimezone(UTC)


def test_freeze_requires_owner_approval_and_binds_hashes_once(repository: ArenaRepository) -> None:
    project = repository.create_project("Test", project_id="project")
    repository.register_artifact("a" * 64, size_bytes=1, storage_uri="local://a")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", "a" * 64)
    experiment = repository.create_experiment(project, pack, "experiment", experiment_id="experiment-one")
    definition, spec_hash = _frozen_definition(experiment, "a" * 64)
    with pytest.raises(FrozenExperimentError):
        repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash="a" * 64)
    repository.set_experiment_owner_approval(experiment, "approved")
    repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash="a" * 64)
    repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash="a" * 64)
    mismatched = dict(definition)
    mismatched["claim_ceiling"] = "tampered"
    with pytest.raises(FrozenExperimentError, match="different definition"):
        repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=mismatched, spec_hash=spec_hash, study_pack_hash="a" * 64)


def test_experiment_provenance_rejects_cross_project_pack_and_predecessor(repository: ArenaRepository) -> None:
    project_one = repository.create_project("One", project_id="one")
    project_two = repository.create_project("Two", project_id="two")
    repository.register_artifact("a" * 64, size_bytes=1, storage_uri="local://a")
    pack_one = repository.create_study_pack_version(project_one, "pack", "1.0.0", "a" * 64)
    pack_two = repository.create_study_pack_version(project_two, "pack", "1.0.0", "a" * 64)
    with pytest.raises(ValueError, match="study pack"):
        repository.create_experiment(project_two, pack_one, "cross-project")
    predecessor = repository.create_experiment(project_one, pack_one, "predecessor")
    with pytest.raises(ValueError, match="predecessor"):
        repository.create_experiment(project_two, pack_two, "cross-project-predecessor", predecessor_id=predecessor)
    with pytest.raises(ValueError, match="predecessor"):
        repository.create_experiment(project_two, pack_two, "missing-predecessor", predecessor_id="missing")
    with pytest.raises(ValueError, match="own predecessor"):
        repository.create_experiment(project_one, pack_one, "self-predecessor", experiment_id="self-predecessor", predecessor_id="self-predecessor")


def test_freeze_rejects_digest_not_owned_by_referenced_study_pack(repository: ArenaRepository) -> None:
    project = repository.create_project("Test", project_id="project")
    repository.register_artifact("a" * 64, size_bytes=1, storage_uri="local://a")
    repository.register_artifact("b" * 64, size_bytes=1, storage_uri="local://b")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", "a" * 64)
    experiment = repository.create_experiment(project, pack, "experiment", owner_approval="approved", experiment_id="experiment-one")
    definition, spec_hash = _frozen_definition(experiment, "a" * 64)
    with pytest.raises(FrozenExperimentError, match="study_pack_hash"):
        repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash="b" * 64)


def test_freeze_rejects_invalid_frozen_definition_without_persisting(repository: ArenaRepository) -> None:
    project = repository.create_project("Test", project_id="project")
    repository.register_artifact("a" * 64, size_bytes=1, storage_uri="local://a")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", "a" * 64)
    experiment = repository.create_experiment(project, pack, "experiment", owner_approval="approved", experiment_id="experiment-one")
    definition, spec_hash = _frozen_definition(experiment, "a" * 64)
    definition["freeze_hash"] = "b" * 64
    with pytest.raises(FrozenExperimentError, match="freeze_hash"):
        repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash="a" * 64)
    with repository.engine.connect() as conn:
        row = conn.execute(select(experiments.c.definition, experiments.c.frozen_at).where(experiments.c.id == experiment)).one()
    assert row.definition == {}
    assert row.frozen_at is None


def test_freeze_requires_definition_timestamp(repository: ArenaRepository) -> None:
    project = repository.create_project("Test", project_id="project")
    repository.register_artifact("a" * 64, size_bytes=1, storage_uri="local://a")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", "a" * 64)
    experiment = repository.create_experiment(project, pack, "experiment", owner_approval="approved", experiment_id="experiment-one")
    definition, spec_hash = _frozen_definition(experiment, "a" * 64)
    definition.pop("frozen_at")
    with pytest.raises(FrozenExperimentError, match="frozen_at"):
        repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash="a" * 64)


def test_freeze_rejects_stale_expected_definition_and_preserves_newer_draft(repository: ArenaRepository) -> None:
    project = repository.create_project("Test", project_id="project")
    repository.register_artifact("a" * 64, size_bytes=1, storage_uri="local://a")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", "a" * 64)
    expected = {"revision": "expected"}
    changed = {"revision": "changed"}
    experiment = repository.create_experiment(project, pack, "experiment", owner_approval="approved", definition=expected, experiment_id="experiment-one")
    definition, spec_hash = _frozen_definition(experiment, "a" * 64)
    repository.update_experiment_definition(experiment, changed)
    with pytest.raises(FrozenExperimentError, match="definition changed before freeze"):
        repository.freeze_experiment(experiment, expected_definition=expected, frozen_definition=definition, spec_hash=spec_hash, study_pack_hash="a" * 64)
    with repository.engine.connect() as conn:
        row = conn.execute(select(experiments.c.definition, experiments.c.frozen_at).where(experiments.c.id == experiment)).one()
    assert row.definition == changed
    assert row.frozen_at is None


def test_transaction_rolls_back(repository: ArenaRepository) -> None:
    with pytest.raises(RuntimeError), repository.transaction() as conn:
        conn.execute(projects.insert().values(id="rolled-back", name="Nope"))
        raise RuntimeError("abort")
    with repository.engine.connect() as conn:
        assert conn.execute(select(projects.c.id).where(projects.c.id == "rolled-back")).scalar_one_or_none() is None


def test_foreign_keys_and_immutable_versions(repository: ArenaRepository) -> None:
    with pytest.raises(IntegrityError):
        repository.create_study_pack_version("missing", "pack", "1.0.0", "a" * 64)
    project = repository.create_project("Test", project_id="project")
    repository.register_artifact("a" * 64, size_bytes=1, storage_uri="local://a")
    repository.create_study_pack_version(project, "pack", "1.0.0", "a" * 64)
    with pytest.raises(ImmutableVersionConflict):
        repository.create_study_pack_version(project, "pack", "1.0.0", "a" * 64)
    with pytest.raises(ValueError, match="semantic version"):
        repository.create_study_pack_version(project, "pack", "one", "a" * 64)


def test_unknown_cost_is_null_and_reconciled_cost_requires_evidence(repository: ArenaRepository) -> None:
    _, attempt, _ = _frozen_attempt(repository)
    # The ledger FK requires the execution created by _frozen_attempt, so recover it from the attempt chain.
    with repository.engine.connect() as conn:
        execution_id = conn.execute(select(episodes.c.execution_id).join(attempts, attempts.c.episode_id == episodes.c.id).where(attempts.c.id == attempt)).scalar_one()
    with repository.transaction() as conn:
        conn.execute(usage_ledger.insert().values(id="unknown", execution_id=execution_id, attempt_id=attempt, model_id="model", cost_status="unknown", cost_usd=None))
    with pytest.raises(IntegrityError), repository.transaction() as conn:
        conn.execute(usage_ledger.insert().values(id="bad-unknown", execution_id=execution_id, attempt_id=attempt, model_id="model", cost_status="unknown", cost_usd=0))
    with pytest.raises(IntegrityError), repository.transaction() as conn:
        conn.execute(usage_ledger.insert().values(id="bad-reconciled", execution_id=execution_id, attempt_id=attempt, model_id="model", cost_status="reconciled", cost_usd=1, actual_cost_usd=1))
    with repository.transaction() as conn:
        conn.execute(usage_ledger.insert().values(id="reconciled", execution_id=execution_id, attempt_id=attempt, model_id="model", input_tokens=1, output_tokens=2, total_tokens=3, context_tokens=1, tool_calls=0, cost_status="reconciled", cost_usd=1, actual_cost_usd=1, price_catalog_revision="2026-08-14", provider_usage_digest="d" * 64))


def test_event_sequence_is_monotonic_under_sqlite_race(repository: ArenaRepository) -> None:
    _, attempt, _ = _frozen_attempt(repository)
    with ThreadPoolExecutor(max_workers=4) as executor:
        sequences = list(executor.map(lambda _: repository.append_attempt_event(attempt, "tick"), range(12)))
    assert sorted(sequences) == list(range(1, 13))
    assert [event["sequence"] for event in repository.list_attempt_events(attempt)] == list(range(1, 13))


def test_execution_cursor_interleaves_attempts_without_loss_or_reuse(repository: ArenaRepository) -> None:
    _, first_attempt, _ = _frozen_attempt(repository)
    with repository.engine.connect() as conn:
        episode_id, execution_id = conn.execute(
            select(attempts.c.episode_id, episodes.c.execution_id)
            .join(episodes, attempts.c.episode_id == episodes.c.id)
            .where(attempts.c.id == first_attempt)
        ).one()
    second_attempt = repository.create_attempt(episode_id, 1)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(
            lambda index: repository.append_attempt_event(
                first_attempt if index % 2 else second_attempt,
                "tick",
                {"index": index},
            ),
            range(16),
        ))

    events = repository.list_execution_events_after(execution_id, 0)
    assert [event["execution_sequence"] for event in events] == list(range(1, 17))
    assert {event["attempt_id"] for event in events} == {first_attempt, second_attempt}
    assert [event["sequence"] for event in repository.list_attempt_events(first_attempt)] == list(range(1, 9))
    assert [event["sequence"] for event in repository.list_attempt_events(second_attempt)] == list(range(1, 9))

    with repository.transaction() as conn:
        conn.execute(attempt_events.delete().where(attempt_events.c.execution_sequence == 8))
    repository.append_attempt_event(first_attempt, "after-gap")
    tailed = repository.list_execution_events_after(execution_id, 7)
    assert [event["execution_sequence"] for event in tailed] == list(range(9, 18))
    assert len({event["id"] for event in tailed}) == len(tailed)
    assert repository.list_execution_events_after(execution_id, 99) == []
    with pytest.raises(ValueError, match="cursor"):
        repository.list_execution_events_after(execution_id, -1)
    with pytest.raises(ValueError, match="does not exist"):
        repository.append_attempt_event("missing-attempt", "invalid")


def test_execution_event_list_fails_closed_for_denormalized_execution_mismatch(repository: ArenaRepository) -> None:
    _, attempt, experiment = _frozen_attempt(repository)
    with repository.engine.connect() as conn:
        actual_execution = conn.execute(
            select(episodes.c.execution_id)
            .select_from(attempts.join(episodes, attempts.c.episode_id == episodes.c.id))
            .where(attempts.c.id == attempt)
        ).scalar_one()
    other_execution = repository.create_execution(experiment)
    with repository.transaction() as conn:
        conn.execute(attempt_events.insert().values(
            id="cross-execution-event", attempt_id=attempt, execution_id=other_execution,
            sequence=1, execution_sequence=1, event_type="invalid", payload={},
        ))
    with pytest.raises(ValueError, match="integrity mismatch"):
        repository.list_execution_events_after(other_execution, 0)
    with pytest.raises(ValueError, match="integrity mismatch"):
        repository.list_execution_events_after(actual_execution, 0)


def test_sqlite_rejects_multiple_workers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="worker_concurrency"):
        create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}", worker_concurrency=2)
