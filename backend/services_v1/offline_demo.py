"""Personal-profile runner for the exact bundled offline demonstration.

This service is intentionally narrower than the normal execution API.  It
never accepts a filesystem path, command, adapter, provider, provenance body,
or task configuration from a browser.  The only runnable payload is the
repository-bundled, synthetic offline-demo fixture.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from adapters_v1 import AdapterRegistry
from adapters_v1.offline_fixture import (
    OFFLINE_DEMO_ADAPTER_DIGEST,
    OfflineDemoFixtureAdapter,
    OfflineDemoFixtureStateOracle,
    bundled_study_pack_root,
)
from arena_cli.provenance import collect_study_pack_provenance
from artifacts_v1 import ArtifactStore
from evaluation_v1 import EvaluationWorker, TrustedGraderRegistry
from execution_v1 import DurableWorker
from persistence_v1 import ArenaRepository
from persistence_v1.schema import executions, idempotency_records, jobs, offline_demo_admissions, offline_demo_runtime_locks
from protocol_v1 import ExecutionProvenance, ExperimentSpec, StudyPack
from protocol_v1.canonical import canonical_json

from .execution import ExecutionError, ExecutionService
from .registry import ProtocolRegistryService, RegistryError

_EXPECTED_ATTEMPTS = 80
_MAX_RUN_SECONDS = 120.0
_LOCK_SCOPE = "bundled-offline-demo-v1"
_REQUEST_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class OfflineDemoError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class OfflineDemoService:
    """Run only the hash-bound bundled fixture in a personal local project."""

    def __init__(
        self,
        repository: ArenaRepository,
        artifact_store: ArtifactStore,
        registry_service: ProtocolRegistryService,
        *,
        personal_project_id: str,
        repository_root: Path,
        fixture_registry: AdapterRegistry,
        enabled: bool,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.registry_service = registry_service
        self.personal_project_id = personal_project_id
        self.repository_root = repository_root.resolve()
        self.fixture_registry = fixture_registry
        self.enabled = enabled
        self.execution_service = ExecutionService(
            repository,
            artifact_store,
            personal_project_id=personal_project_id,
            adapter_registry=fixture_registry,
        )
        self._tasks: set[asyncio.Task[None]] = set()
        self._task_lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        repository: ArenaRepository,
        artifact_store: ArtifactStore,
        registry_service: ProtocolRegistryService,
        *,
        personal_project_id: str,
        repository_root: Path,
        enabled: bool,
    ) -> "OfflineDemoService":
        fixture_registry = AdapterRegistry()
        await fixture_registry.install_trusted(
            OfflineDemoFixtureAdapter(), OFFLINE_DEMO_ADAPTER_DIGEST,
        )
        service = cls(
            repository,
            artifact_store,
            registry_service,
            personal_project_id=personal_project_id,
            repository_root=repository_root,
            fixture_registry=fixture_registry,
            enabled=enabled,
        )
        service._ensure_runtime_lock()
        return service

    def start(self, *, project_id: str | None) -> dict[str, Any]:
        """Import the exact canonical pack; this never freezes or executes it."""
        self._require_personal(project_id)
        manifest = self._manifest_bytes()
        try:
            imported = self.registry_service.import_pack(
                manifest,
                "application/json",
                project_id=self.personal_project_id,
            )
        except RegistryError as exc:
            raise OfflineDemoError(
                "offline_demo_import_hold",
                "The bundled offline demonstration could not be imported.",
                status_code=exc.status_code,
            ) from exc
        return {
            "study_pack_id": imported["study_pack_id"],
            "version": imported["version"],
            "idempotent_replay": imported["idempotent_replay"],
            "execution_started": False,
            "claim_ceiling": "bundled synthetic fixture imported only; no execution or outcome evidence",
        }

    async def execute(
        self,
        experiment_id: str,
        *,
        project_id: str | None,
        request_key: str | None,
    ) -> dict[str, Any]:
        """Dispatch one verified fixture execution and drive only its leases."""
        self._require_personal(project_id)
        if not request_key or not _REQUEST_KEY.fullmatch(request_key):
            raise OfflineDemoError(
                "idempotency_key_required",
                "Use an idempotency key of at most 128 letters, numbers, dots, colons, underscores, or hyphens.",
            )
        return await self._execute_locked(experiment_id, request_key=request_key)

    async def _execute_locked(self, experiment_id: str, *, request_key: str) -> dict[str, Any]:
        """Create or recover under the request's observed-provenance lock."""
        self._validate_exact_frozen_demo(experiment_id)
        try:
            admission = self._admit_request(experiment_id, request_key)
            if "busy" in admission:
                raise OfflineDemoError("offline_demo_busy", str(admission["busy"]), status_code=409)
            canonical_request_key = str(admission["request_key"])
            existing_execution_id = admission.get("execution_id")
            if isinstance(existing_execution_id, str):
                replay = self._execution_response(existing_execution_id)
                if replay is None:
                    raise OfflineDemoError(
                        "offline_demo_idempotency_conflict",
                        "The prior offline demonstration request cannot be safely replayed.",
                        status_code=409,
                    )
                if replay["fixture_execution_scheduled"]:
                    await self._schedule(existing_execution_id)
                return replay
            provenance = ExecutionProvenance.model_validate_json(canonical_json(admission["provenance"]))
            created = self.execution_service.create_execution(
                experiment_id,
                provenance.model_dump(mode="json"),
                project_id=self.personal_project_id,
                request_key=canonical_request_key,
            )
            self._bind_execution(str(admission["id"]), str(created["execution_id"]))
        except OfflineDemoError:
            raise
        except (ExecutionError, ValueError, OSError) as exc:
            status = exc.status_code if isinstance(exc, ExecutionError) else 409
            raise OfflineDemoError(
                "offline_demo_execution_hold",
                "The exact bundled fixture cannot be dispatched from its current durable state.",
                status_code=status,
            ) from exc
        if created["expected_attempts"] != _EXPECTED_ATTEMPTS:
            raise OfflineDemoError(
                "offline_demo_attempt_bound",
                "The bundled demonstration did not produce its fixed attempt count.",
                status_code=409,
            )
        await self._schedule(str(created["execution_id"]))
        return {
            **created,
            "provider_execution_started_by_request": False,
            "fixture_execution_scheduled": True,
            "claim_ceiling": "bundled synthetic fixture execution only; no provider, live-model, or causal evidence",
        }

    async def close(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _require_personal(self, project_id: str | None) -> None:
        if not self.enabled or project_id not in {None, self.personal_project_id}:
            raise OfflineDemoError(
                "offline_demo_personal_only",
                "The bundled offline demonstration is available only in the personal profile.",
                status_code=403,
            )

    def _manifest_path(self) -> Path:
        return bundled_study_pack_root() / "study-pack.json"

    def _manifest_bytes(self) -> bytes:
        try:
            expected = StudyPack.model_validate_json(self._manifest_path().read_bytes())
            return canonical_json(expected.model_dump(mode="json"))
        except (OSError, ValueError) as exc:
            raise OfflineDemoError(
                "offline_demo_unavailable",
                "The bundled offline demonstration is unavailable.",
                status_code=503,
            ) from exc

    def _validate_exact_frozen_demo(self, experiment_id: str) -> None:
        try:
            spec, stored_pack = self.execution_service._load_frozen_experiment(  # noqa: SLF001 - exact durable binding authority
                self.personal_project_id,
                experiment_id,
            )
            expected_pack = StudyPack.model_validate_json(self._manifest_path().read_bytes())
        except (ExecutionError, OSError, ValueError) as exc:
            raise OfflineDemoError(
                "offline_demo_frozen_binding_required",
                "A frozen exact bundled demonstration experiment is required.",
                status_code=409,
            ) from exc
        if canonical_json(stored_pack.model_dump(mode="json")) != canonical_json(expected_pack.model_dump(mode="json")):
            raise OfflineDemoError(
                "offline_demo_pack_mismatch",
                "The selected experiment is not bound to the exact bundled demonstration.",
                status_code=409,
            )
        expected_spec = expected_pack.experiments[0].model_copy(update={
            # The experiment identifier and predecessor are registry metadata,
            # not fixture behavior. A user may choose an immutable clone name;
            # every behavior-bearing field remains byte-for-byte compared.
            "experiment_id": spec.experiment_id,
            "predecessor_experiment_id": spec.predecessor_experiment_id,
        })
        if not self._same_unfrozen_definition(spec, expected_spec):
            raise OfflineDemoError(
                "offline_demo_experiment_mismatch",
                "The selected frozen experiment is not the bundled demonstration definition.",
                status_code=409,
            )

    @staticmethod
    def _same_unfrozen_definition(actual: ExperimentSpec, expected: ExperimentSpec) -> bool:
        reset = {
            "frozen": False,
            "frozen_at": None,
            "freeze_hash": None,
            "study_pack_hash": None,
        }
        actual_payload = actual.model_dump(mode="json")
        expected_payload = expected.model_dump(mode="json")
        actual_payload.update(reset)
        expected_payload.update(reset)
        return canonical_json(actual_payload) == canonical_json(expected_payload)

    def _ensure_runtime_lock(self) -> None:
        """Create the singleton lock once; the admission transaction locks it."""
        try:
            with self.repository.transaction(immediate=True) as connection:
                connection.execute(insert(offline_demo_runtime_locks).values(scope=_LOCK_SCOPE))
        except IntegrityError:
            # A concurrent service created the same immutable singleton row.
            return

    def _admit_request(self, experiment_id: str, request_key: str) -> dict[str, Any]:
        """Reserve the one fixture slot and persist first provenance before execution creation."""
        self._ensure_runtime_lock()
        with self.repository.transaction(immediate=True) as connection:
            lock = connection.execute(select(offline_demo_runtime_locks).where(
                offline_demo_runtime_locks.c.scope == _LOCK_SCOPE,
            ).with_for_update()).mappings().one()
            existing = connection.execute(select(offline_demo_admissions).where(
                offline_demo_admissions.c.project_id == self.personal_project_id,
                offline_demo_admissions.c.key == request_key,
            )).mappings().first()
            if existing is not None and str(existing["experiment_id"]) != experiment_id:
                raise OfflineDemoError("offline_demo_idempotency_conflict", "This idempotency key is already bound to a different experiment.", status_code=409)
            # A completed original key remains an idempotent replay even if a
            # later run for the same experiment owns the singleton lock.
            if existing is not None and isinstance(existing["execution_id"], str):
                return self._admission_payload(existing)
            active = None
            if lock["admission_id"]:
                active = connection.execute(select(offline_demo_admissions).where(
                    offline_demo_admissions.c.id == lock["admission_id"],
                )).mappings().first()
            if active is not None:
                active_execution = active["execution_id"]
                if not isinstance(active_execution, str):
                    active_execution = self._recover_bound_execution(connection, active)
                if isinstance(active_execution, str):
                    status = connection.execute(select(executions.c.status).where(executions.c.id == active_execution)).scalar_one_or_none()
                    if status in _TERMINAL_STATUSES:
                        connection.execute(update(offline_demo_runtime_locks).where(offline_demo_runtime_locks.c.scope == _LOCK_SCOPE).values(admission_id=None))
                        active = None
                    else:
                        if str(active["experiment_id"]) == experiment_id:
                            # A browser may have lost its original key after a
                            # restart. Recover this live admission only.
                            return self._admission_payload(active, execution_id=active_execution)
                        return {"busy": "The local bundled fixture is already running or awaiting explicit recovery."}
                elif active is not None:
                    if str(active["experiment_id"]) == experiment_id:
                        return self._admission_payload(active)
                    # An unbound reservation is never released on a clock. The
                    # original key can explicitly recover it; all other work is
                    # held until that binding reaches a terminal state.
                    return {"busy": "The local bundled fixture is being prepared or awaits recovery for its original experiment."}
            if existing is not None:
                return self._admission_payload(existing)
            if existing is None:
                admission_id = f"x{uuid.uuid4().hex}"
                connection.execute(insert(offline_demo_admissions).values(
                    id=admission_id,
                    project_id=self.personal_project_id,
                    key=request_key,
                    experiment_id=experiment_id,
                    provenance=None,
                    reservation_expires_at=None,
                ))
                existing = {"id": admission_id, "provenance": None, "execution_id": None}
            connection.execute(update(offline_demo_runtime_locks).where(
                offline_demo_runtime_locks.c.scope == _LOCK_SCOPE,
            ).values(admission_id=str(existing["id"])))
            provenance = existing["provenance"]
            if provenance is None:
                provenance = collect_study_pack_provenance(
                    repository_root=self.repository_root,
                    study_pack_path=self._manifest_path(),
                ).provenance.model_dump(mode="json")
                connection.execute(update(offline_demo_admissions).where(
                    offline_demo_admissions.c.id == str(existing["id"]),
                ).values(provenance=provenance))
            return {"id": str(existing["id"]), "request_key": request_key, "provenance": provenance, "execution_id": existing["execution_id"]}

    @staticmethod
    def _admission_payload(admission: Mapping[str, Any], *, execution_id: str | None = None) -> dict[str, Any]:
        return {
            "id": str(admission["id"]),
            "request_key": str(admission["key"]),
            "provenance": admission["provenance"],
            "execution_id": execution_id if execution_id is not None else admission["execution_id"],
        }

    def _recover_bound_execution(self, connection: Any, admission: Mapping[str, Any]) -> str | None:
        """Close create-before-bind crash window from generic durable authority."""
        response = connection.execute(select(idempotency_records.c.response).where(
            idempotency_records.c.project_id == admission["project_id"],
            idempotency_records.c.key == admission["key"],
        )).scalar_one_or_none()
        execution_id = dict(response or {}).get("execution_id")
        if not isinstance(execution_id, str):
            return None
        if connection.execute(select(executions.c.id).where(executions.c.id == execution_id)).scalar_one_or_none() is None:
            return None
        connection.execute(update(offline_demo_admissions).where(
            offline_demo_admissions.c.id == admission["id"],
            offline_demo_admissions.c.execution_id.is_(None),
        ).values(execution_id=execution_id, reservation_expires_at=None))
        return execution_id

    def _bind_execution(self, admission_id: str, execution_id: str) -> None:
        with self.repository.transaction(immediate=True) as connection:
            bound = connection.execute(update(offline_demo_admissions).where(
                offline_demo_admissions.c.id == admission_id,
                offline_demo_admissions.c.execution_id.is_(None),
            ).values(execution_id=execution_id, reservation_expires_at=None))
            if bound.rowcount != 1:
                existing = connection.execute(select(offline_demo_admissions.c.execution_id).where(
                    offline_demo_admissions.c.id == admission_id,
                )).scalar_one_or_none()
                if existing != execution_id:
                    raise OfflineDemoError("offline_demo_idempotency_conflict", "The offline demonstration admission changed before it could be bound.", status_code=409)

    def _execution_response(self, execution_id: str) -> dict[str, Any] | None:
        with self.repository.engine.connect() as connection:
            row = connection.execute(select(executions).where(executions.c.id == execution_id)).mappings().first()
            attempt_jobs = connection.execute(select(jobs.c.id).where(jobs.c.execution_id == execution_id, jobs.c.kind == "attempt")).scalars().all()
        if row is None or len(attempt_jobs) != _EXPECTED_ATTEMPTS:
            return None
        return {
            "execution_id": execution_id,
            "expected_attempts": _EXPECTED_ATTEMPTS,
            "job_ids": [str(job_id) for job_id in attempt_jobs],
            "idempotent_replay": True,
            "provider_execution_started_by_request": False,
            "fixture_execution_scheduled": row["status"] not in _TERMINAL_STATUSES,
            "claim_ceiling": "replayed bundled synthetic fixture execution only; no provider, live-model, or causal evidence",
        }

    def _recoverable_execution(self, experiment_id: str) -> dict[str, Any] | None:
        """Find one interrupted fixture run without broad queue inspection."""
        with self.repository.engine.connect() as connection:
            rows = connection.execute(select(executions).where(
                executions.c.experiment_id == experiment_id,
                executions.c.status.in_(("queued", "running")),
            ).order_by(executions.c.created_at, executions.c.id)).mappings().all()
        if not rows:
            return None
        if len(rows) != 1:
            raise OfflineDemoError(
                "offline_demo_recovery_ambiguous",
                "More than one unfinished bundled demonstration requires durable review before recovery.",
                status_code=409,
            )
        execution = dict(rows[0])
        execution_id = str(execution["id"])
        with self.repository.engine.connect() as connection:
            attempt_jobs = connection.execute(select(jobs.c.id, jobs.c.payload).where(
                jobs.c.execution_id == execution_id,
                jobs.c.kind == "attempt",
            )).mappings().all()
        if len(attempt_jobs) != _EXPECTED_ATTEMPTS or not all(self._is_fixture_attempt_job(row) for row in attempt_jobs):
            raise OfflineDemoError(
                "offline_demo_recovery_hold",
                "The unfinished execution is not the exact bundled fixture job set.",
                status_code=409,
            )
        return {
            "execution_id": execution_id,
            "expected_attempts": _EXPECTED_ATTEMPTS,
            "job_ids": [str(row["id"]) for row in attempt_jobs],
            "idempotent_replay": True,
            "provider_execution_started_by_request": False,
            "fixture_execution_scheduled": True,
            "claim_ceiling": "recovered bundled synthetic fixture execution only; no provider, live-model, or causal evidence",
        }

    @staticmethod
    def _is_fixture_attempt_job(row: Mapping[str, Any]) -> bool:
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            return False
        harness = payload.get("harness")
        return isinstance(harness, Mapping) and harness.get("adapter_identity") == "offline-demo-fixture" and harness.get("adapter_digest") == OFFLINE_DEMO_ADAPTER_DIGEST

    async def _schedule(self, execution_id: str) -> None:
        async with self._task_lock:
            if any(task.get_name() == execution_id and not task.done() for task in self._tasks):
                return
            task = asyncio.create_task(self._drive(execution_id), name=execution_id)
            self._tasks.add(task)
            task.add_done_callback(self._finish_task)

    def _finish_task(self, task: asyncio.Task[None]) -> None:
        """Observe every task exception so a failed driver is never silent."""
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            # _drive records the durable recovery detail before an exception
            # reaches this observer. Retrieving it here prevents an
            # unobserved-task warning from concealing that detail.
            return

    async def _drive(self, execution_id: str) -> None:
        """Do not block an API request or lease any execution other than this one."""
        worker = DurableWorker(
            self.repository,
            self.fixture_registry,
            self.artifact_store,
            state_oracle=OfflineDemoFixtureStateOracle(),
            project_id=self.personal_project_id,
        )
        evaluator = EvaluationWorker(
            self.repository,
            self.artifact_store,
            TrustedGraderRegistry(),
            project_id=self.personal_project_id,
        )
        owner = f"offline-demo-{uuid.uuid4().hex}"
        try:
            async with asyncio.timeout(_MAX_RUN_SECONDS):
                completed_attempts = 0
                while True:
                    if await worker.run_once(owner, execution_id=execution_id):
                        completed_attempts += 1
                        if completed_attempts > _EXPECTED_ATTEMPTS:
                            raise RuntimeError("offline demo attempt bound exceeded")
                    elif self._has_pending_jobs(execution_id, kind="attempt"):
                        await asyncio.sleep(0.25)
                    else:
                        break
                completed_evaluations = 0
                while True:
                    if await asyncio.to_thread(evaluator.run_once, owner, execution_id=execution_id):
                        completed_evaluations += 1
                        if completed_evaluations > _EXPECTED_ATTEMPTS:
                            raise RuntimeError("offline demo evaluation bound exceeded")
                    elif self._has_pending_jobs(execution_id, kind="evaluation"):
                        await asyncio.sleep(0.25)
                    else:
                        break
                with self.repository.engine.connect() as connection:
                    status = connection.execute(select(executions.c.status).where(executions.c.id == execution_id)).scalar_one()
                if status not in _TERMINAL_STATUSES:
                    raise RuntimeError("offline demo has no runnable jobs but execution is not terminal")
        except TimeoutError:
            self._cancel_pending(execution_id)
            self._record_interruption(execution_id, "offline_demo_worker_timeout")
            raise RuntimeError("offline demo worker deadline exceeded") from None
        except asyncio.CancelledError:
            self._cancel_pending(execution_id)
            self._record_interruption(execution_id, "offline_demo_worker_interrupted")
            raise
        except Exception:
            self._cancel_pending(execution_id)
            self._record_interruption(execution_id, "offline_demo_worker_failed")
            raise
        finally:
            self._release_terminal_admission(execution_id)

    def _has_pending_jobs(self, execution_id: str, *, kind: str) -> bool:
        """A live lease or reclaim backoff is pending, not a finished execution."""
        with self.repository.engine.connect() as connection:
            return connection.execute(select(jobs.c.id).where(
                jobs.c.execution_id == execution_id,
                jobs.c.kind == kind,
                jobs.c.status.not_in(_TERMINAL_STATUSES),
            ).limit(1)).first() is not None

    def _release_terminal_admission(self, execution_id: str) -> None:
        """Release only a terminal execution; expiry never frees a live run."""
        with self.repository.transaction(immediate=True) as connection:
            status = connection.execute(select(executions.c.status).where(
                executions.c.id == execution_id,
            )).scalar_one_or_none()
            if status not in _TERMINAL_STATUSES:
                return
            admission_id = connection.execute(select(offline_demo_admissions.c.id).where(
                offline_demo_admissions.c.execution_id == execution_id,
            )).scalar_one_or_none()
            if admission_id is not None:
                connection.execute(update(offline_demo_runtime_locks).where(
                    offline_demo_runtime_locks.c.scope == _LOCK_SCOPE,
                    offline_demo_runtime_locks.c.admission_id == admission_id,
                ).values(admission_id=None))

    def _record_interruption(self, execution_id: str, code: str) -> None:
        """Keep a durable, user-triggered recovery instruction with the run."""
        with self.repository.transaction() as connection:
            row = connection.execute(select(executions.c.parameters, executions.c.status).where(
                executions.c.id == execution_id,
            )).mappings().first()
            if row is None:
                return
            parameters = dict(row["parameters"] or {})
            recoverable = row["status"] not in _TERMINAL_STATUSES
            parameters["offline_demo_recovery"] = {
                "code": code,
                "recoverable": recoverable,
                "action": "resume_bundled_offline_demo" if recoverable else "start_new_bundled_offline_demo",
            }
            connection.execute(update(executions).where(
                executions.c.id == execution_id,
            ).values(parameters=parameters))

    def _cancel_pending(self, execution_id: str) -> None:
        """Persist a visible cancellation state without touching other jobs."""
        from persistence_v1.jobs import JobLeaseRepository
        from persistence_v1.schema import jobs

        with self.repository.engine.connect() as connection:
            job_ids = connection.execute(
                jobs.select().with_only_columns(jobs.c.id).where(
                    jobs.c.execution_id == execution_id,
                    jobs.c.status.in_(("queued", "running")),
                ),
            ).scalars().all()
        leases = JobLeaseRepository(self.repository)
        for job_id in job_ids:
            leases.request_cancel(str(job_id))
        with self.repository.transaction(immediate=True) as connection:
            # This authority checks all jobs in this execution and leaves
            # live leases pending until their owners or recovery settle them.
            leases._finalize_execution_if_terminal(connection, execution_id, now=datetime.now(UTC))
