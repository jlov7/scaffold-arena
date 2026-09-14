"""Lease-driven evaluator worker. It never invokes adapters or providers."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Self

from sqlalchemy import select

from artifacts_v1 import ArtifactStore
from evaluation_v1.graders import TrustedGraderRegistry
from persistence_v1 import ArenaRepository
from persistence_v1.jobs import JobLease, JobLeaseRepository
from persistence_v1.schema import attempts, episodes, executions, experiments


@dataclass(frozen=True)
class EvaluationWorkerResult:
    job_id: str
    status: str
    detail: str | None = None


class EvaluationWorker:
    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore,
                 registry: TrustedGraderRegistry, *, project_id: str | None = None) -> None:
        self.repository = repository
        self.jobs = JobLeaseRepository(repository)
        self.project_id = project_id
        # Keep service orchestration out of evaluation_v1 import initialization.
        from services_v1.evaluation import DurableEvaluationService

        self.service = DurableEvaluationService(repository, artifact_store, registry)

    def run_once(
        self,
        owner: str,
        *,
        lease_seconds: float = 30.0,
        execution_id: str | None = None,
    ) -> EvaluationWorkerResult | None:
        lease = self.jobs.claim(
            owner,
            lease_seconds=lease_seconds,
            kind="evaluation",
            project_id=self.project_id,
            execution_id=execution_id,
        )
        if lease is None:
            return None
        if lease.attempt_id is None:
            status = self.jobs.finalize_auxiliary(lease.id, owner, outcome="failed", lease_token=lease.token)
            return EvaluationWorkerResult(lease.id, status or "lost", "evaluation job has no attempt")
        try:
            project_id = self._project(lease.attempt_id)
            with _EvaluationLeaseHeartbeat(self.jobs, lease, lease_seconds):
                self.service.evaluate(project_id, lease.attempt_id, lease=lease)
        except Exception as exc:  # noqa: BLE001
            status = self.jobs.finalize_auxiliary(lease.id, owner, outcome="failed", lease_token=lease.token)
            return EvaluationWorkerResult(lease.id, status or "lost", type(exc).__name__)
        status = self.jobs.finalize_auxiliary(lease.id, owner, outcome="completed", lease_token=lease.token)
        return EvaluationWorkerResult(lease.id, status or "lost")

    def _project(self, attempt_id: str) -> str:
        with self.repository.engine.connect() as conn:
            project_id = conn.execute(select(experiments.c.project_id).join(
                executions, executions.c.experiment_id == experiments.c.id
            ).join(episodes, episodes.c.execution_id == executions.c.id).join(
                attempts, attempts.c.episode_id == episodes.c.id
            ).where(attempts.c.id == attempt_id)).scalar_one_or_none()
        if project_id is None:
            raise LookupError("attempt project is unavailable")
        return str(project_id)


class _EvaluationLeaseHeartbeat:
    """Best-effort liveness only; the database token remains the fence."""

    def __init__(self, jobs: JobLeaseRepository, lease: JobLease, lease_seconds: float) -> None:
        self._jobs = jobs
        self._lease = lease
        self._lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=min(1.0, self._lease_seconds))

    def _run(self) -> None:
        interval = min(1.0, max(0.05, self._lease_seconds / 3))
        while not self._stop.wait(interval):
            if not self._jobs.heartbeat(
                self._lease.id,
                self._lease.owner,
                lease_token=self._lease.token,
                lease_seconds=self._lease_seconds,
            ):
                return
