"""Database-authoritative leasing for durable worker jobs."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, func, insert, or_, select, update

from adapters_v1.models import AttemptInput
from protocol_v1.canonical import canonical_json, sha256

from .repository import ArenaRepository, append_attempt_event_in_transaction
from .schema import attempts, episodes, executions, experiments, jobs

TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})
RETRYABLE_FAILURE_CLASSIFICATIONS = frozenset({
    "transient",  # trusted worker/protocol metadata predating adapter classifications
    "transient_adapter",
    "transient_provider",
})
DECLARED_TRANSIENT_ADAPTER_CLASSIFICATIONS = frozenset({
    "transient_adapter",
    "transient_provider",
})
NON_SUCCESS_ATTEMPT_STATUSES = frozenset({"failed", "timed_out", "incomplete"})

# Lease expiry remains the authoritative fencing boundary for heartbeats,
# finalization, and external invocation admission. Reclaim is intentionally
# delayed so the worker supervisor (which polls at most once per second) can
# cancel a stale adapter call before another worker can dispatch the same job.
SUPERVISOR_MAX_POLL_SECONDS = 1.0
LEASE_RECLAIM_GRACE_SECONDS = 2.0
LEASE_RECLAIM_BACKOFF_BASE_SECONDS = 2.0
LEASE_RECLAIM_BACKOFF_CAP_SECONDS = 8.0
MAX_LEASE_GENERATIONS = 5

if LEASE_RECLAIM_GRACE_SECONDS <= SUPERVISOR_MAX_POLL_SECONDS:
    raise RuntimeError("lease reclaim grace must exceed the supervisor poll interval")


def _now() -> datetime:
    return datetime.now(UTC)


def _expired(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= now


def _reclaim_backoff(generation: int) -> timedelta:
    """Deterministic bounded delay before a reclaimed lease can be claimed."""
    exponent = max(0, generation - 1)
    seconds = min(
        LEASE_RECLAIM_BACKOFF_BASE_SECONDS * (2 ** exponent),
        LEASE_RECLAIM_BACKOFF_CAP_SECONDS,
    )
    return timedelta(seconds=seconds)


def _id() -> str:
    return f"x{uuid.uuid4().hex}"


@dataclass(frozen=True)
class JobLease:
    id: str
    execution_id: str
    attempt_id: str | None
    kind: str
    owner: str
    token: str
    expires_at: datetime
    attempt_count: int
    payload: Mapping[str, Any]


class JobLeaseRepository:
    """Lease operations whose compare-and-set conditions live in the database."""

    def __init__(self, engine: Engine | ArenaRepository):
        self.engine = engine.engine if isinstance(engine, ArenaRepository) else engine
        self._repository = ArenaRepository(self.engine)

    def enqueue(
        self, execution_id: str, *, attempt_id: str | None, kind: str = "attempt",
        payload: Mapping[str, Any] | None = None, job_id: str | None = None,
        available_at: datetime | None = None,
    ) -> str:
        job_id = job_id or _id()
        with self._repository.transaction() as conn:
            if attempt_id is not None:
                attempt_execution_id = conn.execute(
                    select(episodes.c.execution_id)
                    .select_from(attempts.join(episodes, attempts.c.episode_id == episodes.c.id))
                    .where(attempts.c.id == attempt_id)
                ).scalar_one_or_none()
                if attempt_execution_id != execution_id:
                    raise ValueError("attempt job must belong to its execution")
            conn.execute(insert(jobs).values(
                id=job_id, execution_id=execution_id, attempt_id=attempt_id, kind=kind,
                status="queued", attempt_count=0, available_at=available_at or _now(), payload=dict(payload or {}),
            ))
        return job_id

    def claim(self, owner: str, *, lease_seconds: float, now: datetime | None = None,
              kind: str | None = None, project_id: str | None = None,
              execution_id: str | None = None) -> JobLease | None:
        if not owner or lease_seconds <= 0:
            raise ValueError("owner and positive lease_seconds are required")
        if project_id is not None and not project_id:
            raise ValueError("project_id must be non-empty when provided")
        if execution_id is not None and not execution_id:
            raise ValueError("execution_id must be non-empty when provided")
        now = now or _now()
        expires_at = now + timedelta(seconds=lease_seconds)
        with self._repository.transaction(immediate=True) as conn:
            self._reclaim_expired_in_transaction(conn, now=now, project_id=project_id, execution_id=execution_id)
            query = select(jobs).where(
                jobs.c.status == "queued",
                or_(jobs.c.available_at.is_(None), jobs.c.available_at <= now),
            ).order_by(jobs.c.created_at, jobs.c.id)
            if project_id is not None:
                query = query.select_from(
                    jobs.join(executions, jobs.c.execution_id == executions.c.id).join(
                        experiments, executions.c.experiment_id == experiments.c.id,
                    )
                ).where(experiments.c.project_id == project_id)
            if kind is not None:
                query = query.where(jobs.c.kind == kind)
            if execution_id is not None:
                query = query.where(jobs.c.execution_id == execution_id)
            if self.engine.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = conn.execute(query.limit(1)).mappings().first()
            if row is None:
                return None
            token = uuid.uuid4().hex
            changed = conn.execute(update(jobs).where(
                jobs.c.id == row["id"], jobs.c.status == "queued",
            ).values(
                status="running", lease_owner=owner, lease_token=token, lease_expires_at=expires_at,
                heartbeat_at=now, attempt_count=func.coalesce(jobs.c.attempt_count, 0) + 1,
            ))
            if changed.rowcount != 1:
                return None
            return JobLease(
                id=str(row["id"]), execution_id=str(row["execution_id"]), attempt_id=row["attempt_id"],
                kind=str(row["kind"]), owner=owner, token=token, expires_at=expires_at,
                attempt_count=int(row["attempt_count"] or 0) + 1, payload=dict(row["payload"] or {}),
            )

    @staticmethod
    def _project_job_ids(project_id: str):
        return select(jobs.c.id).select_from(
            jobs.join(executions, jobs.c.execution_id == executions.c.id).join(
                experiments, executions.c.experiment_id == experiments.c.id,
            )
        ).where(experiments.c.project_id == project_id)

    def heartbeat(self, job_id: str, owner: str, *, lease_token: str, lease_seconds: float, now: datetime | None = None) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = now or _now()
        with self._repository.transaction(immediate=True) as conn:
            query = select(jobs.c.lease_expires_at).where(
                jobs.c.id == job_id, jobs.c.status == "running", jobs.c.lease_owner == owner,
                jobs.c.lease_token == lease_token,
            )
            if self.engine.dialect.name == "postgresql":
                query = query.with_for_update()
            expires_at = conn.execute(query).scalar_one_or_none()
            if _expired(expires_at, now):
                return False
            result = conn.execute(update(jobs).where(
                jobs.c.id == job_id, jobs.c.status == "running", jobs.c.lease_owner == owner,
                jobs.c.lease_token == lease_token,
            ).values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds)))
        return result.rowcount == 1

    def reclaim_expired(self, *, now: datetime | None = None) -> int:
        now = now or _now()
        with self._repository.transaction(immediate=True) as conn:
            return self._reclaim_expired_in_transaction(conn, now=now)

    def _reclaim_expired_in_transaction(
        self,
        conn: Any,
        *,
        now: datetime,
        project_id: str | None = None,
        execution_id: str | None = None,
    ) -> int:
        """Reclaim only after a supervisor-cancellation window has elapsed."""
        reclaim_cutoff = now - timedelta(seconds=LEASE_RECLAIM_GRACE_SECONDS)
        query = select(jobs).where(
            jobs.c.status == "running",
            jobs.c.lease_expires_at.is_not(None),
            jobs.c.lease_expires_at <= reclaim_cutoff,
        ).order_by(jobs.c.created_at, jobs.c.id)
        if project_id is not None:
            query = query.where(jobs.c.id.in_(self._project_job_ids(project_id)))
        if execution_id is not None:
            query = query.where(jobs.c.execution_id == execution_id)
        if self.engine.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)

        reclaimed = 0
        terminal_execution_ids: set[str] = set()
        for row in conn.execute(query).mappings():
            generation = int(row["attempt_count"] or 0)
            condition = (
                jobs.c.id == row["id"],
                jobs.c.status == "running",
                jobs.c.lease_expires_at.is_not(None),
                jobs.c.lease_expires_at <= reclaim_cutoff,
            )
            if generation >= MAX_LEASE_GENERATIONS:
                changed = conn.execute(update(jobs).where(*condition).values(
                    status="failed",
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                    available_at=None,
                ))
                if changed.rowcount != 1:
                    continue
                reclaimed += 1
                terminal_execution_ids.add(str(row["execution_id"]))
                self._record_lease_generation_exhausted(conn, row, now=now, generation=generation)
                continue

            changed = conn.execute(update(jobs).where(*condition).values(
                status="queued",
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=None,
                available_at=now + _reclaim_backoff(generation),
            ))
            reclaimed += int(changed.rowcount or 0)

        for execution_id in terminal_execution_ids:
            self._finalize_execution_if_terminal(conn, execution_id, now=now)
        return reclaimed

    def _record_lease_generation_exhausted(
        self, conn: Any, job: Mapping[str, Any], *, now: datetime, generation: int,
    ) -> None:
        attempt_id = job["attempt_id"]
        if attempt_id is None:
            return
        attempt = conn.execute(select(attempts.c.result_metadata).where(
            attempts.c.id == attempt_id,
        )).mappings().first()
        metadata = dict(attempt["result_metadata"] or {}) if attempt is not None else {}
        metadata.update({
            "error_code": "lease_generation_exhausted",
            "failure_classification": "permanent_protocol",
            "lease_generation": generation,
            "max_lease_generations": MAX_LEASE_GENERATIONS,
            "lease_expired_at": job["lease_expires_at"].isoformat(),
            "reclaimed_at": now.isoformat(),
        })
        conn.execute(update(attempts).where(attempts.c.id == attempt_id).values(
            status="incomplete",
            result_metadata=metadata,
        ))
        payload = {
            "error_code": "lease_generation_exhausted",
            "lease_generation": generation,
            "max_lease_generations": MAX_LEASE_GENERATIONS,
        }
        self._append_event(conn, str(attempt_id), "lease_generation_exhausted", payload)
        self._append_event(conn, str(attempt_id), "terminal", {
            "winner": "failed",
            "reported_outcome": "incomplete",
            **payload,
        })

    @staticmethod
    def _finalize_execution_if_terminal(conn: Any, execution_id: str, *, now: datetime) -> None:
        remaining = conn.execute(select(func.count()).select_from(jobs).where(
            jobs.c.execution_id == execution_id,
            jobs.c.status.not_in(TERMINAL_JOB_STATUSES),
        )).scalar_one()
        if remaining:
            return
        statuses = set(conn.execute(select(jobs.c.status).where(
            jobs.c.execution_id == execution_id,
        )).scalars())
        execution_status = (
            "completed" if statuses == {"completed"}
            else "cancelled" if statuses == {"cancelled"}
            else "failed"
        )
        conn.execute(update(executions).where(executions.c.id == execution_id).values(
            status=execution_status,
            completed_at=now,
        ))

    def request_cancel(self, job_id: str, *, now: datetime | None = None) -> bool:
        now = now or _now()
        with self._repository.transaction(immediate=True) as conn:
            row = conn.execute(select(jobs.c.status, jobs.c.attempt_id).where(jobs.c.id == job_id)).first()
            if row is None or row.status in TERMINAL_JOB_STATUSES:
                return False
            if row.status == "queued":
                result = conn.execute(update(jobs).where(jobs.c.id == job_id, jobs.c.status == "queued").values(
                    status="cancelled", cancel_requested_at=now,
                ))
                if result.rowcount and row.attempt_id is not None:
                    conn.execute(update(attempts).where(attempts.c.id == row.attempt_id).values(status="cancelled", result_metadata={"cancelled_before_dispatch": True}))
                    self._append_event(conn, row.attempt_id, "terminal", {"winner": "cancelled", "reported_outcome": "cancelled"})
                return result.rowcount == 1
            result = conn.execute(update(jobs).where(
                jobs.c.id == job_id, jobs.c.status == "running",
            ).values(cancel_requested_at=now))
            return result.rowcount == 1

    def cancel_requested(self, job_id: str, owner: str, *, lease_token: str) -> bool | None:
        """Return None if the caller no longer owns a live lease."""
        with self.engine.connect() as conn:
            row = conn.execute(select(jobs.c.status, jobs.c.lease_owner, jobs.c.lease_token, jobs.c.cancel_requested_at).where(jobs.c.id == job_id)).first()
        if row is None or row.status != "running" or row.lease_owner != owner or row.lease_token != lease_token:
            return None
        return row.cancel_requested_at is not None

    def finalize(
        self, job_id: str, owner: str, *, outcome: str, attempt_status: str,
        result_metadata: Mapping[str, Any] | None = None, now: datetime | None = None,
        lease_token: str,
        followup_kind: str | None = None, followup_payload: Mapping[str, Any] | None = None,
    ) -> str | None:
        """Atomically choose the terminal winner and record its attempt evidence."""
        if outcome not in {"completed", "failed", "cancelled"}:
            raise ValueError("invalid job outcome")
        now = now or _now()
        with self._repository.transaction(immediate=True) as conn:
            row = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
            if row is None:
                raise KeyError(job_id)
            if row["status"] in TERMINAL_JOB_STATUSES:
                return str(row["status"])
            if row["status"] != "running" or row["lease_owner"] != owner or row["lease_token"] != lease_token or _expired(row["lease_expires_at"], now):
                return None
            winner = "cancelled" if row["cancel_requested_at"] is not None else outcome
            final_attempt_status = "cancelled" if winner == "cancelled" else attempt_status
            changed = conn.execute(update(jobs).where(
                jobs.c.id == job_id, jobs.c.status == "running", jobs.c.lease_owner == owner,
                jobs.c.lease_token == lease_token,
                jobs.c.lease_expires_at > now,
            ).values(status=winner, lease_owner=None, lease_token=None, lease_expires_at=None, heartbeat_at=now))
            if changed.rowcount != 1:
                return None
            if row["attempt_id"] is not None:
                conn.execute(update(attempts).where(attempts.c.id == row["attempt_id"]).values(
                    status=final_attempt_status, result_metadata=dict(result_metadata or {}),
                ))
                self._append_event(conn, row["attempt_id"], "terminal", {"winner": winner, "reported_outcome": attempt_status})
            if followup_kind is not None:
                if row["attempt_id"] is None:
                    raise ValueError("follow-up job requires an attempt-bound lease")
                followup_id = f"ev-{sha256({'attempt_id': row['attempt_id'], 'kind': followup_kind})[:60]}"
                existing = conn.execute(select(jobs.c.id).where(
                    jobs.c.attempt_id == row["attempt_id"], jobs.c.kind == followup_kind,
                )).scalar_one_or_none()
                if existing is None:
                    conn.execute(insert(jobs).values(
                        id=followup_id, execution_id=row["execution_id"], attempt_id=row["attempt_id"],
                        kind=followup_kind, status="queued", attempt_count=0, available_at=now,
                        payload=dict(followup_payload or {}),
                    ))
            remaining = conn.execute(select(func.count()).select_from(jobs).where(
                jobs.c.execution_id == row["execution_id"], jobs.c.status.not_in(TERMINAL_JOB_STATUSES),
            )).scalar_one()
            if not remaining:
                statuses = set(conn.execute(select(jobs.c.status).where(jobs.c.execution_id == row["execution_id"])).scalars())
                execution_status = "completed" if statuses == {"completed"} else "cancelled" if statuses == {"cancelled"} else "failed"
                conn.execute(update(executions).where(executions.c.id == row["execution_id"]).values(status=execution_status, completed_at=now))
            return winner

    def finalize_with_followup(
        self, job_id: str, owner: str, *, outcome: str, attempt_status: str,
        followup_kind: str, result_metadata: Mapping[str, Any] | None = None,
        followup_payload: Mapping[str, Any] | None = None, now: datetime | None = None,
        lease_token: str,
    ) -> str | None:
        """Atomically terminalize an attempt and queue its dependent durable job."""
        return self.finalize(
            job_id, owner, outcome=outcome, attempt_status=attempt_status,
            result_metadata=result_metadata, now=now, followup_kind=followup_kind,
            lease_token=lease_token,
            followup_payload=followup_payload,
        )

    @staticmethod
    def _append_event(conn: Any, attempt_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        append_attempt_event_in_transaction(conn, attempt_id, event_type, payload)

    def record_diagnostic(self, attempt_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        """Safe diagnostic event; caller supplies only redacted fields."""
        with self._repository.transaction(immediate=True) as conn:
            self._append_event(conn, attempt_id, event_type, payload)

    def complete(self, job_id: str, owner: str, *, lease_token: str, result_metadata: Mapping[str, Any] | None = None) -> str | None:
        return self.finalize(job_id, owner, outcome="completed", attempt_status="completed", result_metadata=result_metadata, lease_token=lease_token)

    def finalize_auxiliary(self, job_id: str, owner: str, *, outcome: str,
                           lease_token: str, now: datetime | None = None) -> str | None:
        """Finalize a non-attempt job without changing attempt evidence or status."""
        if outcome not in {"completed", "failed", "cancelled"}:
            raise ValueError("invalid job outcome")
        now = now or _now()
        with self._repository.transaction(immediate=True) as conn:
            row = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
            if row is None:
                raise KeyError(job_id)
            if row["status"] in TERMINAL_JOB_STATUSES:
                return str(row["status"])
            if row["status"] != "running" or row["lease_owner"] != owner or row["lease_token"] != lease_token or _expired(row["lease_expires_at"], now):
                return None
            winner = "cancelled" if row["cancel_requested_at"] is not None else outcome
            changed = conn.execute(update(jobs).where(
                jobs.c.id == job_id, jobs.c.status == "running", jobs.c.lease_owner == owner,
                jobs.c.lease_token == lease_token,
                jobs.c.lease_expires_at > now,
            ).values(status=winner, lease_owner=None, lease_token=None, lease_expires_at=None, heartbeat_at=now))
            if changed.rowcount != 1:
                return None
            remaining = conn.execute(select(func.count()).select_from(jobs).where(
                jobs.c.execution_id == row["execution_id"], jobs.c.status.not_in(TERMINAL_JOB_STATUSES),
            )).scalar_one()
            if not remaining:
                statuses = set(conn.execute(select(jobs.c.status).where(jobs.c.execution_id == row["execution_id"])).scalars())
                execution_status = "completed" if statuses == {"completed"} else "cancelled" if statuses == {"cancelled"} else "failed"
                conn.execute(update(executions).where(executions.c.id == row["execution_id"]).values(status=execution_status, completed_at=now))
            return winner

    def fail(self, job_id: str, owner: str, *, lease_token: str, attempt_status: str = "failed", result_metadata: Mapping[str, Any] | None = None) -> str | None:
        return self.finalize(job_id, owner, outcome="failed", attempt_status=attempt_status, result_metadata=result_metadata, lease_token=lease_token)

    def retry(self, job_id: str, *, now: datetime | None = None) -> tuple[str, str]:
        """Create a fresh attempt/job; prior attempt evidence remains immutable."""
        now = now or _now()
        with self._repository.transaction(immediate=True) as conn:
            job = conn.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
            if job is None or job["attempt_id"] is None or job["kind"] != "attempt":
                raise ValueError("retry requires an attempt job")
            old = conn.execute(select(attempts).where(attempts.c.id == job["attempt_id"])).mappings().one()
            result_metadata = dict(old["result_metadata"] or {})
            classification = result_metadata.get("failure_classification")
            if old["status"] not in NON_SUCCESS_ATTEMPT_STATUSES:
                raise ValueError("retry requires a non-success terminal attempt")
            captured_adapter_terminal = result_metadata.get("captured_adapter_terminal") is True
            captured_retry = (
                job["status"] == "completed"
                and captured_adapter_terminal
                and classification in DECLARED_TRANSIENT_ADAPTER_CLASSIFICATIONS
            )
            worker_retry = (
                job["status"] == "failed"
                and not captured_adapter_terminal
                and classification in RETRYABLE_FAILURE_CLASSIFICATIONS
            )
            if not (captured_retry or worker_retry):
                raise ValueError("retry requires a persisted transient failure classification")
            ordinal = int(conn.execute(select(func.coalesce(func.max(attempts.c.ordinal), -1)).where(attempts.c.episode_id == old["episode_id"])).scalar_one()) + 1
            attempt_id, next_job_id = _id(), _id()
            payload = dict(job["payload"] or {})
            raw_input = payload.get("attempt_input")
            if not isinstance(raw_input, dict):
                raise TypeError("retry requires a persisted attempt input")
            try:
                original_input = AttemptInput.model_validate_json(canonical_json(raw_input))
            except (TypeError, ValueError) as exc:
                raise ValueError("retry requires a valid persisted attempt input") from exc
            if original_input.attempt.attempt_id != old["id"] or original_input.attempt.episode_id != old["episode_id"]:
                raise ValueError("retry attempt input does not bind the failed attempt")
            used = int(conn.execute(
                select(func.count()).select_from(attempts).where(attempts.c.episode_id == old["episode_id"])
            ).scalar_one())
            if used >= original_input.attempt.budget.max_attempts:
                raise ValueError("retry would exceed the declared attempt budget")
            request_hash = sha256({
                "retry_of_request_hash": original_input.attempt.request_hash,
                "retry_of_attempt_id": old["id"],
                "attempt_id": attempt_id,
                "episode_id": old["episode_id"],
                "ordinal": ordinal + 1,
            })
            envelope = original_input.attempt.model_copy(update={
                "attempt_id": attempt_id,
                "ordinal": ordinal + 1,
                "request_hash": request_hash,
                "status": "queued",
                "queued_at": now,
                "started_at": None,
                "completed_at": None,
                "observed_provider_version": None,
                "observed_endpoint_digest": None,
                "response_hash": None,
            })
            rebound_input = AttemptInput.bind(original_input.scenario, envelope)
            metadata = dict(old["request_metadata"] or {})
            metadata["retry_of_attempt_id"] = old["id"]
            metadata["envelope"] = rebound_input.attempt.model_dump(mode="json")
            conn.execute(insert(attempts).values(id=attempt_id, episode_id=old["episode_id"], ordinal=ordinal, status="queued", request_metadata=metadata))
            payload["attempt_input"] = rebound_input.model_dump(mode="json")
            conn.execute(insert(jobs).values(id=next_job_id, execution_id=job["execution_id"], attempt_id=attempt_id, kind=job["kind"], status="queued", attempt_count=0, available_at=now, payload=payload))
            conn.execute(update(executions).where(executions.c.id == job["execution_id"]).values(status="queued", completed_at=None))
        return attempt_id, next_job_id
