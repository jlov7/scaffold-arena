from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, update

from adapters_v1 import AdapterRegistry
from adapters_v1.offline_fixture import OFFLINE_DEMO_ADAPTER_DIGEST, OfflineDemoFixtureAdapter
from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.jobs import JobLeaseRepository, MAX_LEASE_GENERATIONS
from persistence_v1.schema import attempt_events, attempts, episodes, executions, idempotency_records, jobs, offline_demo_admissions, offline_demo_runtime_locks
from protocol_v1 import ExecutionProvenance, StudyPack
from protocol_v1.canonical import canonical_json
from services_v1 import ExecutionService, OfflineDemoError, OfflineDemoService, ProtocolRegistryService


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACK_PATH = REPOSITORY_ROOT / "study_packs" / "offline-demo-v1" / "study-pack.json"


async def _fixture_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    await registry.install_trusted(OfflineDemoFixtureAdapter(), OFFLINE_DEMO_ADAPTER_DIGEST)
    return registry


async def _service(tmp_path: Path) -> tuple[OfflineDemoService, ProtocolRegistryService, ArenaRepository, LocalArtifactStore]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    store = LocalArtifactStore(tmp_path / "artifacts")
    adapters = await _fixture_registry()
    registry = ProtocolRegistryService(repository, store, personal_project_id="personal", adapter_registry=adapters)
    service = await OfflineDemoService.create(
        repository,
        store,
        registry,
        personal_project_id="personal",
        repository_root=REPOSITORY_ROOT,
        enabled=True,
    )
    return service, registry, repository, store


def _frozen_clone(registry: ProtocolRegistryService, experiment_id: str, *, changed: bool = False) -> None:
    spec = StudyPack.model_validate_json(PACK_PATH.read_bytes()).experiments[0].model_copy(update={
        "experiment_id": experiment_id,
    })
    payload = spec.model_dump(mode="json")
    if changed:
        payload["sampling"]["max_tokens"] = int(payload["sampling"]["max_tokens"]) - 1
    registry.create_experiment(payload, project_id="personal")
    registry.freeze(experiment_id, project_id="personal")
    assert registry.preflight(experiment_id, project_id="personal")["verdict"] == "PASS"


def _test_provenance() -> dict[str, object]:
    return {
        "code_revision": "offline-demo-service-test",
        "code_hash": "a" * 64,
        "runtime_image": "offline-fixture-runtime",
        "runtime_image_hash": "b" * 64,
        "environment_hash": "c" * 64,
        "prompt_hash": "d" * 64,
        "context_hash": "e" * 64,
        "tool_hash": "f" * 64,
        "source_refs": [{"source_uri": "synthetic://offline-demo", "content_hash": "0" * 64}],
        "captured_at": "2026-09-13T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_offline_demo_drives_only_requested_execution_and_reuses_observed_provenance(tmp_path: Path) -> None:
    service, registry, repository, store = await _service(tmp_path)
    try:
        started = service.start(project_id="personal")
        assert started["execution_started"] is False
        _frozen_clone(registry, "my-immutable-demo")
        _frozen_clone(registry, "unrelated-immutable-demo")

        unrelated = ExecutionService(
            repository,
            store,
            personal_project_id="personal",
            adapter_registry=service.fixture_registry,
        ).create_execution(
            "unrelated-immutable-demo",
            _test_provenance(),
            project_id="personal",
            request_key="unrelated-queued-work",
        )

        first, duplicate = await asyncio.gather(
            service.execute("my-immutable-demo", project_id="personal", request_key="browser-retry"),
            service.execute("my-immutable-demo", project_id="personal", request_key="browser-retry"),
        )
        assert first["execution_id"] == duplicate["execution_id"]
        execution_id = str(first["execution_id"])
        with repository.engine.connect() as connection:
            captured = connection.execute(select(executions.c.parameters).where(
                executions.c.id == execution_id,
            )).scalar_one()
        assert isinstance(captured, dict)
        assert "provenance" in captured
        ExecutionProvenance.model_validate_json(canonical_json(captured["provenance"]))
        await asyncio.gather(*tuple(service._tasks))
        with repository.engine.connect() as connection:
            completed_parameters = connection.execute(select(executions.c.parameters).where(
                executions.c.id == execution_id,
            )).scalar_one()
        ExecutionProvenance.model_validate_json(canonical_json(completed_parameters["provenance"]))

        replay = await service.execute("my-immutable-demo", project_id="personal", request_key="browser-retry")
        assert replay["execution_id"] == execution_id
        with repository.engine.connect() as connection:
            target = connection.execute(select(executions.c.status, executions.c.parameters).where(
                executions.c.id == execution_id,
            )).mappings().one()
            unrelated_jobs = connection.execute(select(jobs.c.status).where(
                jobs.c.execution_id == unrelated["execution_id"],
                jobs.c.kind == "attempt",
            )).scalars().all()
        assert target["status"] == "completed"
        assert len(unrelated_jobs) == 80
        assert set(unrelated_jobs) == {"queued"}
        assert target["parameters"]["provenance"]["captured_at"]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_offline_demo_rejects_altered_or_team_experiments(tmp_path: Path) -> None:
    service, registry, _repository, _store = await _service(tmp_path)
    try:
        service.start(project_id="personal")
        _frozen_clone(registry, "altered-immutable-demo", changed=True)
        with pytest.raises(OfflineDemoError, match="not the bundled demonstration definition"):
            await service.execute("altered-immutable-demo", project_id="personal", request_key="altered")
        with pytest.raises(OfflineDemoError, match="personal profile"):
            service.start(project_id="team")
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_offline_demo_shared_database_serializes_first_capture_and_global_fixture_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_one, registry, repository, store = await _service(tmp_path)
    service_two = await OfflineDemoService.create(
        repository, store, registry, personal_project_id="personal", repository_root=REPOSITORY_ROOT, enabled=True,
    )
    captures: list[str] = []

    def capture(**_kwargs):
        captures.append("capture")
        return type("Captured", (), {"provenance": ExecutionProvenance.model_validate_json(canonical_json(_test_provenance()))})()

    async def do_not_drive(_execution_id: str) -> None:
        return None

    monkeypatch.setattr("services_v1.offline_demo.collect_study_pack_provenance", capture)
    monkeypatch.setattr(service_one, "_schedule", do_not_drive)
    monkeypatch.setattr(service_two, "_schedule", do_not_drive)
    try:
        service_one.start(project_id="personal")
        _frozen_clone(registry, "shared-demo-a")
        _frozen_clone(registry, "shared-demo-b")
        first, replay = await asyncio.gather(
            service_one.execute("shared-demo-a", project_id="personal", request_key="shared-capture"),
            service_two.execute("shared-demo-a", project_id="personal", request_key="shared-capture"),
        )
        assert first["execution_id"] == replay["execution_id"]
        assert captures == ["capture"]
        with pytest.raises(OfflineDemoError, match="already running"):
            await service_two.execute("shared-demo-b", project_id="personal", request_key="different-key")
        with repository.engine.connect() as connection:
            admissions = connection.execute(select(offline_demo_admissions)).mappings().all()
            lock = connection.execute(select(offline_demo_runtime_locks.c.admission_id)).scalar_one()
        assert len(admissions) == 1
        assert admissions[0]["execution_id"] == first["execution_id"]
        assert lock == admissions[0]["id"]
    finally:
        await service_one.close()
        await service_two.close()


@pytest.mark.asyncio
async def test_unbound_admission_never_expires_into_a_second_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, registry, repository, store = await _service(tmp_path)
    service_two = await OfflineDemoService.create(
        repository, store, registry, personal_project_id="personal", repository_root=REPOSITORY_ROOT, enabled=True,
    )
    calls = 0

    def capture(**_kwargs):
        nonlocal calls
        calls += 1
        payload = _test_provenance() | {"captured_at": f"2026-09-13T00:00:0{calls}Z"}
        return type("Captured", (), {"provenance": ExecutionProvenance.model_validate_json(canonical_json(payload))})()

    async def do_not_drive(_execution_id: str) -> None:
        return None

    monkeypatch.setattr("services_v1.offline_demo.collect_study_pack_provenance", capture)
    monkeypatch.setattr(service, "_schedule", do_not_drive)
    monkeypatch.setattr(service_two, "_schedule", do_not_drive)
    try:
        service.start(project_id="personal")
        _frozen_clone(registry, "paused-demo-a")
        _frozen_clone(registry, "paused-demo-b")
        # Service one has admitted A and is paused before create_execution.
        admitted = service._admit_request("paused-demo-a", "original-key")
        with repository.transaction(immediate=True) as connection:
            connection.execute(offline_demo_admissions.update().where(
                offline_demo_admissions.c.id == admitted["id"],
            ).values(reservation_expires_at=datetime(2000, 1, 1, tzinfo=UTC)))
        with pytest.raises(OfflineDemoError, match="being prepared"):
            await service_two.execute("paused-demo-b", project_id="personal", request_key="different-key")
        # The original caller resumes. A new browser key for the same
        # experiment then recovers this admission, including original capture.
        created = await service.execute("paused-demo-a", project_id="personal", request_key="original-key")
        recovered = await service_two.execute("paused-demo-a", project_id="personal", request_key="new-browser-key")
        assert created["execution_id"] == recovered["execution_id"]
        with repository.engine.connect() as connection:
            ids = connection.execute(select(executions.c.id)).scalars().all()
            admission = connection.execute(select(offline_demo_admissions).where(
                offline_demo_admissions.c.id == admitted["id"],
            )).mappings().one()
            record_key = connection.execute(select(idempotency_records.c.key).where(
                idempotency_records.c.project_id == "personal",
            )).scalar_one()
        assert ids == [created["execution_id"]]
        assert admission["key"] == "original-key"
        assert record_key == "original-key"
        assert calls == 1
    finally:
        await service.close()
        await service_two.close()


@pytest.mark.asyncio
async def test_expired_unbound_admission_reconciles_created_execution_before_other_key_runs(tmp_path: Path) -> None:
    service, registry, repository, _store = await _service(tmp_path)
    try:
        service.start(project_id="personal")
        _frozen_clone(registry, "crash-demo-a")
        _frozen_clone(registry, "crash-demo-b")
        admitted = service._admit_request("crash-demo-a", "crash-key")
        provenance = ExecutionProvenance.model_validate_json(canonical_json(admitted["provenance"]))
        created = service.execution_service.create_execution(
            "crash-demo-a", provenance.model_dump(mode="json"), project_id="personal", request_key="crash-key",
        )
        # Simulate process loss after generic execution commit but before the
        # admission could be bound. Expiry alone must not free the fixture.
        with repository.transaction(immediate=True) as connection:
            connection.execute(offline_demo_admissions.update().where(
                offline_demo_admissions.c.id == admitted["id"],
            ).values(reservation_expires_at=datetime(2000, 1, 1, tzinfo=UTC)))
        with pytest.raises(OfflineDemoError, match="already running"):
            await service.execute("crash-demo-b", project_id="personal", request_key="other-key")
        with repository.engine.connect() as connection:
            bound = connection.execute(select(offline_demo_admissions.c.execution_id).where(
                offline_demo_admissions.c.id == admitted["id"],
            )).scalar_one()
        assert bound == created["execution_id"]
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_terminal_original_key_replays_without_replacing_new_same_experiment_admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, registry, repository, _store = await _service(tmp_path)

    async def do_not_drive(_execution_id: str) -> None:
        return None

    monkeypatch.setattr(service, "_schedule", do_not_drive)
    try:
        service.start(project_id="personal")
        _frozen_clone(registry, "terminal-replay-demo")
        first = await service.execute("terminal-replay-demo", project_id="personal", request_key="terminal-key")
        with repository.transaction(immediate=True) as connection:
            connection.execute(executions.update().where(
                executions.c.id == first["execution_id"],
            ).values(status="failed"))
        # A new browser key clears the stale terminal lock and is admitted, but
        # remains paused before execution creation.
        second_admission = service._admit_request("terminal-replay-demo", "new-browser-key")
        assert second_admission["execution_id"] is None
        replay = await service.execute("terminal-replay-demo", project_id="personal", request_key="terminal-key")
        assert replay["execution_id"] == first["execution_id"]
        with repository.engine.connect() as connection:
            ids = connection.execute(select(executions.c.id)).scalars().all()
            lock = connection.execute(select(offline_demo_runtime_locks.c.admission_id)).scalar_one()
        assert ids == [first["execution_id"]]
        assert lock == second_admission["id"]
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("lease_state", ["live", "expired"])
@pytest.mark.parametrize("kind", ["attempt", "evaluation"])
async def test_one_recovery_waits_for_lease_and_backoff_until_real_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lease_state: str, kind: str,
) -> None:
    from adapters_v1.offline_fixture import OfflineDemoFixtureStateOracle
    from execution_v1 import DurableWorker

    service, registry, repository, store = await _service(tmp_path)
    schedule = service._schedule
    async def pause(_execution_id: str) -> None:
        pass
    monkeypatch.setattr(service, "_schedule", pause)
    try:
        service.start(project_id="personal")
        _frozen_clone(registry, "recover-lease")
        created = await service.execute("recover-lease", project_id="personal", request_key="recover")
        execution_id = str(created["execution_id"])
        leases = JobLeaseRepository(repository)
        if kind == "evaluation":
            worker = DurableWorker(repository, service.fixture_registry, store, state_oracle=OfflineDemoFixtureStateOracle(), project_id="personal")
            assert await worker.run_once("first-attempt", execution_id=execution_id)
        lease = leases.claim("lost-process", lease_seconds=0.1, execution_id=execution_id, kind=kind)
        assert lease is not None
        for job_id in created["job_ids"]:
            if job_id != lease.id:
                leases.request_cancel(str(job_id))
        if lease_state == "expired":
            with repository.transaction() as connection:
                connection.execute(update(jobs).where(jobs.c.id == lease.id).values(lease_expires_at=datetime(2000, 1, 1, tzinfo=UTC)))
        monkeypatch.setattr(service, "_schedule", schedule)
        recovered = await service.execute("recover-lease", project_id="personal", request_key="recover")
        assert recovered["execution_id"] == execution_id
        assert recovered["fixture_execution_scheduled"] is True
        assert len(service._tasks) == 1
        await asyncio.wait_for(asyncio.gather(*tuple(service._tasks)), timeout=12)
        with repository.engine.connect() as connection:
            job = connection.execute(select(jobs).where(jobs.c.id == lease.id)).mappings().one()
            status = connection.execute(select(executions.c.status).where(executions.c.id == execution_id)).scalar_one()
            lock = connection.execute(select(offline_demo_runtime_locks.c.admission_id)).scalar_one()
        assert job["status"] == "completed"
        assert job["attempt_count"] == 2
        # Other attempts were deliberately cancelled, so this is not a
        # completed 80-attempt fixture or comparative-result assertion.
        assert status == "failed"
        assert lock is None
        assert not service._tasks
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("generation", [1, MAX_LEASE_GENERATIONS])
async def test_execution_scoped_reclamation_preserves_unrelated_expired_rows(
    tmp_path: Path, generation: int,
) -> None:
    service, registry, repository, _store = await _service(tmp_path)
    try:
        service.start(project_id="personal")
        for name in ("scoped-a", "scoped-b"):
            _frozen_clone(registry, name)
        created = [service.execution_service.create_execution(name, _test_provenance(), project_id="personal", request_key=name) for name in ("scoped-a", "scoped-b")]
        leases = JobLeaseRepository(repository)
        claimed = [leases.claim("lost", lease_seconds=1, execution_id=str(item["execution_id"])) for item in created]
        assert all(claimed)
        with repository.transaction() as connection:
            connection.execute(update(jobs).where(jobs.c.id.in_([item.id for item in claimed])).values(lease_expires_at=datetime(2000, 1, 1, tzinfo=UTC), attempt_count=generation))
        other_id = str(created[1]["execution_id"])
        def snapshot():
            with repository.engine.connect() as connection:
                other_attempts = select(attempts.c.id).join(episodes).where(episodes.c.execution_id == other_id)
                return [
                    [dict(row) for row in connection.execute(query).mappings()]
                    for query in (
                        select(jobs).where(jobs.c.execution_id == other_id).order_by(jobs.c.id),
                        select(executions).where(executions.c.id == other_id),
                        select(attempts).where(attempts.c.id.in_(other_attempts)).order_by(attempts.c.id),
                        select(attempt_events).where(attempt_events.c.attempt_id.in_(other_attempts)).order_by(attempt_events.c.id),
                    )
                ]
        before = snapshot()
        leases.claim("selected", lease_seconds=30, project_id="personal", execution_id=str(created[0]["execution_id"]))
        assert snapshot() == before
        with repository.engine.connect() as connection:
            selected_status = connection.execute(select(jobs.c.status).where(jobs.c.id == claimed[0].id)).scalar_one()
        assert selected_status == ("failed" if generation == MAX_LEASE_GENERATIONS else "queued")
        # A caller that intentionally omits execution scope still reclaims
        # expired work throughout the selected project.
        leases.claim("project", lease_seconds=30, project_id="personal")
        assert snapshot() != before
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_pending_live_lease_timeout_retains_actionable_scoped_cancellation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, registry, repository, _store = await _service(tmp_path)
    async def pause(_execution_id: str) -> None:
        pass
    monkeypatch.setattr(service, "_schedule", pause)
    monkeypatch.setattr("services_v1.offline_demo._MAX_RUN_SECONDS", 0.05)
    try:
        service.start(project_id="personal")
        _frozen_clone(registry, "timed-demo")
        created = await service.execute("timed-demo", project_id="personal", request_key="timed")
        execution_id = str(created["execution_id"])
        leases = JobLeaseRepository(repository)
        lease = leases.claim("live-process", lease_seconds=30, execution_id=execution_id)
        assert lease is not None
        # Only this live job remains pending; the deadline cannot cancel its
        # owner synchronously or report it as successfully completed.
        for job_id in created["job_ids"]:
            if job_id != lease.id:
                leases.request_cancel(str(job_id))
        with pytest.raises(RuntimeError, match="deadline exceeded"):
            await service._drive(execution_id)
        with repository.engine.connect() as connection:
            execution = connection.execute(select(executions).where(executions.c.id == execution_id)).mappings().one()
            job = connection.execute(select(jobs).where(jobs.c.id == lease.id)).mappings().one()
        assert execution["status"] not in {"completed", "failed", "cancelled"}
        assert execution["parameters"]["offline_demo_recovery"]["code"] == "offline_demo_worker_timeout"
        assert execution["parameters"]["offline_demo_recovery"]["action"] == "resume_bundled_offline_demo"
        assert execution["parameters"]["offline_demo_recovery"]["recoverable"] is True
        assert job["status"] == "running" and job["cancel_requested_at"] is not None
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_interruption_finalizes_only_all_cancelled_execution_and_releases_admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, registry, repository, _store = await _service(tmp_path)
    async def pause(_execution_id: str) -> None:
        pass
    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError
    monkeypatch.setattr(service, "_schedule", pause)
    monkeypatch.setattr("services_v1.offline_demo.DurableWorker.run_once", cancelled)
    try:
        service.start(project_id="personal")
        _frozen_clone(registry, "cancelled-demo")
        created = await service.execute("cancelled-demo", project_id="personal", request_key="cancelled-key")
        execution_id = str(created["execution_id"])
        with pytest.raises(asyncio.CancelledError):
            await service._drive(execution_id)
        with repository.engine.connect() as connection:
            execution = connection.execute(select(executions).where(executions.c.id == execution_id)).mappings().one()
            statuses = set(connection.execute(select(jobs.c.status).where(jobs.c.execution_id == execution_id)).scalars())
            lock = connection.execute(select(offline_demo_runtime_locks.c.admission_id)).scalar_one()
        assert statuses == {"cancelled"} and execution["status"] == "cancelled"
        assert execution["completed_at"] is not None
        assert execution["parameters"]["offline_demo_recovery"] == {
            "code": "offline_demo_worker_interrupted", "recoverable": False, "action": "start_new_bundled_offline_demo",
        }
        assert lock is None
        replay = await service.execute("cancelled-demo", project_id="personal", request_key="cancelled-key")
        assert replay["execution_id"] == execution_id and replay["fixture_execution_scheduled"] is False
        rerun = await service.execute("cancelled-demo", project_id="personal", request_key="new-key")
        assert rerun["execution_id"] != execution_id
    finally:
        await service.close()
