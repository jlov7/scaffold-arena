from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from artifacts_v1 import LocalArtifactStore
from persistence_v1 import (
    ArenaRepository,
    create_persistence_engine,
    import_legacy_run,
    metadata,
)
from persistence_v1.schema import attempt_events, audit_events, execution_event_cursors
from protocol_v1 import ExperimentSpec
from protocol_v1 import freeze_experiment as freeze_protocol_experiment


def test_legacy_import_quarantines_raw_bytes_and_records_no_claims(tmp_path: Path) -> None:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    project = repository.create_project("Legacy", project_id="project")
    store = LocalArtifactStore(tmp_path / "artifacts")
    result = import_legacy_run(repository, store, project, {"run_id": "old", "status": "completed"})
    assert result.classification == "legacy_local_unverified"
    assert store.get_bytes(result.artifact_digest)
    with engine.connect() as conn:
        payload = conn.execute(select(audit_events.c.payload).where(audit_events.c.id == result.audit_event_id)).scalar_one()
    assert payload["classification"] == "legacy_local_unverified"
    assert payload["evidence_claims"] == []


def test_metadata_equals_alembic_head(tmp_path: Path) -> None:
    backend_root = Path(__file__).parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migrated.db'}")
    command.upgrade(config, "head")
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    assert set(inspect(engine).get_table_names()) >= set(metadata.tables)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), metadata) == []
    lock_foreign_keys = inspect(engine).get_foreign_keys("offline_demo_runtime_locks")
    assert [(fk["name"], fk["referred_table"]) for fk in lock_foreign_keys] == [
        ("fk_offline_demo_lock_admission", "offline_demo_admissions"),
    ]


def test_prior_baseline_upgrades_add_usage_columns_once(tmp_path: Path) -> None:
    backend_root = Path(__file__).parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'baseline.db'}")
    command.upgrade(config, "20260814_0001")
    command.upgrade(config, "head")
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'baseline.db'}")
    ledger_columns = {column["name"] for column in inspect(engine).get_columns("usage_ledger")}
    catalog_columns = {column["name"] for column in inspect(engine).get_columns("price_catalog")}
    assert {"total_tokens", "context_tokens", "tool_calls", "reserved_max_tokens", "reserved_max_tool_calls"} <= ledger_columns
    assert "billing_profile" in catalog_columns


def test_execution_event_cursor_backfills_legacy_rows_deterministically(tmp_path: Path) -> None:
    backend_root = Path(__file__).parents[2]
    database_url = f"sqlite:///{tmp_path / 'legacy-events.db'}"
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260814_0002")
    legacy_engine = create_persistence_engine(database_url)
    legacy = MetaData()
    legacy.reflect(legacy_engine)
    created_at = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
    with legacy_engine.begin() as conn:
        conn.execute(legacy.tables["projects"].insert().values(id="project", name="Legacy"))
        conn.execute(legacy.tables["artifacts"].insert().values(digest="a" * 64, size_bytes=1, media_type="application/octet-stream", storage_uri="legacy://artifact", metadata_json={}))
        conn.execute(legacy.tables["study_packs"].insert().values(id="pack", project_id="project", pack_key="pack", version="1.0.0", content_digest="a" * 64, content_metadata={}))
        conn.execute(legacy.tables["experiments"].insert().values(id="experiment", project_id="project", study_pack_id="pack", name="Legacy", protocol_version="1.0", owner_approval="approved", definition={}))
        conn.execute(legacy.tables["executions"].insert().values(id="execution", experiment_id="experiment", status="queued", parameters={}))
        conn.execute(legacy.tables["episodes"].insert().values(id="episode", execution_id="execution", ordinal=0, metadata_json={}))
        conn.execute(legacy.tables["attempts"].insert().values(id="attempt-a", episode_id="episode", ordinal=0, request_metadata={}, result_metadata={}))
        conn.execute(legacy.tables["attempts"].insert().values(id="attempt-b", episode_id="episode", ordinal=1, request_metadata={}, result_metadata={}))
        events = legacy.tables["attempt_events"]
        conn.execute(events.insert().values(id="event-b", attempt_id="attempt-b", sequence=1, event_type="legacy", payload={}, created_at=created_at))
        conn.execute(events.insert().values(id="event-a", attempt_id="attempt-a", sequence=1, event_type="legacy", payload={}, created_at=created_at))

    command.upgrade(config, "head")
    engine = create_persistence_engine(database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            select(attempt_events.c.id, attempt_events.c.execution_sequence)
            .where(attempt_events.c.execution_id == "execution")
            .order_by(attempt_events.c.execution_sequence)
        ).all()
        cursor = conn.execute(select(execution_event_cursors.c.last_sequence).where(execution_event_cursors.c.execution_id == "execution")).scalar_one()
    # This is deterministic migration order only: tied legacy timestamps cannot prove observation order.
    assert rows == [("event-a", 1), ("event-b", 2)]
    assert cursor == 2


def test_baseline_migration_does_not_import_live_schema() -> None:
    migration = Path(__file__).parents[2] / "migrations" / "versions" / "20260814_0001_persistence_v1_baseline.py"
    baseline = Path(__file__).parents[2] / "migrations" / "baseline_20260814.py"
    assert "persistence_v1.schema" not in migration.read_text(encoding="utf-8")
    assert "persistence_v1.schema" not in baseline.read_text(encoding="utf-8")


def test_schema_compiles_for_sqlite_and_postgres_without_json_server_defaults() -> None:
    for table in metadata.sorted_tables:
        for dialect in (sqlite.dialect(), postgresql.dialect()):
            statement = str(CreateTable(table).compile(dialect=dialect))
            assert "DEFAULT '{}'" not in statement
            assert "DEFAULT '[]'" not in statement
    jobs = metadata.tables["jobs"]
    for column_name in ("lease_owner", "lease_token", "lease_expires_at", "heartbeat_at", "attempt_count", "available_at", "cancel_requested_at"):
        assert jobs.c[column_name].nullable


@pytest.mark.integration
def test_postgres_contract_when_configured() -> None:
    import os

    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL is not set; Postgres parity is not claimed by this suite")
    engine = create_persistence_engine(url, worker_concurrency=2)
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    project, attempt = _postgres_frozen_attempt(repository)
    assert project
    assert repository.append_attempt_event(attempt, "started") == 1


def _postgres_frozen_attempt(repository: ArenaRepository) -> tuple[str, str]:
    project = repository.create_project("Postgres")
    digest = "b" * 64
    repository.register_artifact(digest, size_bytes=1, storage_uri="test://postgres")
    pack = repository.create_study_pack_version(project, "pack", "1.0.0", digest)
    experiment = repository.create_experiment(project, pack, "exp", owner_approval="approved", experiment_id="experiment-one")
    frozen = freeze_protocol_experiment(
        ExperimentSpec(
            experiment_id=experiment,
            study_pack_id="pack-one",
            scenario_ids=("scenario-one",),
            harness_ids=("harness-one",),
            deterministic_weight=0.7,
            owner_approval="approved",
        ),
        digest,
    )
    repository.freeze_experiment(experiment, expected_definition={}, frozen_definition=frozen.model_dump(mode="json"), spec_hash=str(frozen.freeze_hash), study_pack_hash=digest)
    execution = repository.create_execution(experiment)
    episode = repository.create_episode(execution, 0)
    return project, repository.create_attempt(episode, 0)
