"""Database-authoritative generation fences for external attempt invocations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import BigInteger, cast, func, insert, or_, select, update

from adapters_v1 import AttemptInput, InvocationContext
from persistence_v1 import ArenaRepository
from persistence_v1.invocation_schema import budget_reservations, invocation_records
from persistence_v1.jobs import JobLease
from persistence_v1.schema import jobs
from protocol_v1.canonical import sha256

CancellationState = Literal[
    "not_requested",
    "requested",
    "dispatched",
    "acknowledged",
    "unsupported",
    "unknown",
]
SideEffectState = Literal[
    "not_started",
    "possible",
    "observed",
    "reconciled",
    "ambiguous",
]
UsageState = Literal[
    "not_observed",
    "observed",
    "reconciled",
    "unknown",
    "disputed",
]
AdmissionState = Literal["current", "stale", "duplicate", "ambiguous"]

_CANCEL_RANK: dict[str, int] = {
    "not_requested": 0,
    "requested": 1,
    "dispatched": 2,
    "acknowledged": 3,
    "unsupported": 3,
    "unknown": 3,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _id() -> str:
    return f"iv-{uuid.uuid4().hex}"


def _legacy_provider_request_namespace(provider: str) -> str:
    """Conservative provider-only identity for migrated or unpinned work."""

    return sha256(
        {
            "provider": provider,
            "provider_request_namespace": "legacy-provider-only-v1",
        }
    )


def _provider_request_namespace(
    *,
    provider: str,
    pinned_endpoint_digest: str | None,
) -> str:
    if pinned_endpoint_digest is None:
        return _legacy_provider_request_namespace(provider)
    return sha256(
        {
            "endpoint_digest": pinned_endpoint_digest,
            "provider": provider,
            "provider_request_namespace": "pinned-endpoint-v1",
        }
    )


def _advisory_lock_key(*, domain: str, identity: object) -> int:
    """Return a signed PostgreSQL advisory-lock key without retaining raw identity."""

    unsigned = int(
        sha256({"advisory_lock_domain": domain, "identity": identity})[:16], 16
    )
    return unsigned - (1 << 64) if unsigned >= (1 << 63) else unsigned


class DuplicateProviderRequest(ValueError):
    """Two invocation generations observed the same scoped provider request identity."""


@dataclass(frozen=True)
class InvocationRecord:
    invocation_id: str
    execution_id: str
    attempt_id: str
    job_id: str
    generation: int
    fence_token: str
    provider: str
    provider_model: str
    provider_idempotency_key: str
    provider_request_namespace: str
    provider_request_id: str | None
    lease_owner: str
    lease_acquired_at: datetime
    lease_expires_at: datetime
    dispatch_started_at: datetime | None
    aggregate_deadline_at: datetime | None
    transport_context_state: str
    cancellation_state: CancellationState
    side_effect_state: SideEffectState
    usage_state: UsageState
    admission_state: AdmissionState
    provider_result_digest: str | None
    terminal_outcome: str | None
    terminal_at: datetime | None

    @property
    def context(self) -> InvocationContext:
        return InvocationContext.bind(
            invocation_id=self.invocation_id,
            attempt_id=self.attempt_id,
            generation=self.generation,
            fence_token=self.fence_token,
            provider_idempotency_key=self.provider_idempotency_key,
            aggregate_deadline_at=self.aggregate_deadline_at,
        )


class InvocationRepository:
    """Persist what may have happened outside the database lease boundary."""

    def __init__(self, repository: ArenaRepository):
        self.repository = repository

    def begin(
        self,
        lease: JobLease,
        input: AttemptInput,
        *,
        aggregate_deadline_at: datetime | None = None,
        now: datetime | None = None,
    ) -> InvocationRecord:
        if lease.attempt_id is None or lease.kind != "attempt":
            raise ValueError("external invocation requires an attempt-bound lease")
        if input.attempt.attempt_id != lease.attempt_id:
            raise ValueError("invocation AttemptInput does not bind the leased attempt")
        observed_at = _utc(now or _now())
        deadline = _utc(aggregate_deadline_at) if aggregate_deadline_at else None
        if deadline is not None and deadline <= observed_at:
            raise ValueError("aggregate wall-time deadline has already expired")
        generation = int(lease.attempt_count)
        if generation < 1:
            raise ValueError("invocation generation must be positive")

        with self.repository.transaction(immediate=True) as connection:
            job = connection.execute(
                select(
                    jobs.c.status,
                    jobs.c.lease_owner,
                    jobs.c.lease_token,
                    jobs.c.lease_expires_at,
                    jobs.c.attempt_count,
                ).where(jobs.c.id == lease.id)
            ).first()
            if (
                job is None
                or job.status != "running"
                or job.lease_owner != lease.owner
                or job.lease_token != lease.token
                or job.lease_expires_at is None
                or _utc(job.lease_expires_at) <= observed_at
                or int(job.attempt_count or 0) != generation
            ):
                raise ValueError("invocation requires the current live database lease")

            existing = connection.execute(
                select(invocation_records).where(
                    invocation_records.c.attempt_id == lease.attempt_id,
                    invocation_records.c.generation == generation,
                )
            ).mappings().first()
            if existing is not None:
                if (
                    existing["job_id"] != lease.id
                    or existing["lease_owner"] != lease.owner
                ):
                    raise ValueError("invocation generation is already owned by another lease")
                return self._record(existing)

            prior = connection.execute(
                select(
                    invocation_records.c.id,
                    invocation_records.c.side_effect_state,
                    invocation_records.c.admission_state,
                ).where(
                    invocation_records.c.attempt_id == lease.attempt_id,
                    invocation_records.c.admission_state == "current",
                )
            ).mappings().all()
            for row in prior:
                side_effect_state = (
                    "not_started"
                    if row["side_effect_state"] == "not_started"
                    else "ambiguous"
                )
                connection.execute(
                    update(invocation_records)
                    .where(invocation_records.c.id == row["id"])
                    .values(
                        admission_state="stale",
                        side_effect_state=side_effect_state,
                        updated_at=observed_at,
                    )
                )

            invocation_id = _id()
            fence_token = sha256(
                {
                    "invocation_id": invocation_id,
                    "job_id": lease.id,
                    "attempt_id": lease.attempt_id,
                    "generation": generation,
                    "owner": lease.owner,
                    "nonce": uuid.uuid4().hex,
                }
            )
            provider_idempotency_key = sha256(
                {
                    "attempt_id": lease.attempt_id,
                    "request_hash": input.attempt.request_hash,
                    "provider": input.attempt.provider,
                    "provider_model": input.attempt.provider_model,
                    "endpoint_digest": input.attempt.pinned_endpoint_digest,
                }
            )
            provider_request_namespace = _provider_request_namespace(
                provider=input.attempt.provider,
                pinned_endpoint_digest=input.attempt.pinned_endpoint_digest,
            )
            connection.execute(
                insert(invocation_records).values(
                    id=invocation_id,
                    execution_id=lease.execution_id,
                    attempt_id=lease.attempt_id,
                    job_id=lease.id,
                    generation=generation,
                    fence_token=fence_token,
                    provider=input.attempt.provider,
                    provider_model=input.attempt.provider_model,
                    provider_idempotency_key=provider_idempotency_key,
                    provider_request_namespace=provider_request_namespace,
                    lease_owner=lease.owner,
                    lease_acquired_at=observed_at,
                    lease_expires_at=_utc(lease.expires_at),
                    aggregate_deadline_at=deadline,
                    transport_context_state="unknown",
                    cancellation_state="not_requested",
                    side_effect_state="not_started",
                    usage_state="not_observed",
                    admission_state="current",
                    created_at=observed_at,
                    updated_at=observed_at,
                )
            )
        return self.get(invocation_id)

    def mark_transport_context(
        self,
        invocation: InvocationRecord,
        *,
        supported: bool,
        now: datetime | None = None,
    ) -> InvocationRecord:
        self._update_current(
            invocation,
            values={
                "transport_context_state": "supported" if supported else "unsupported",
                "updated_at": _utc(now or _now()),
            },
        )
        return self.get(invocation.invocation_id)

    def mark_dispatch_started(
        self,
        invocation: InvocationRecord,
        *,
        now: datetime | None = None,
    ) -> InvocationRecord:
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            current = self._locked(connection, invocation)
            if current["side_effect_state"] not in {"not_started", "possible"}:
                raise ValueError("invocation side-effect state cannot move backwards")
            reservation_query = select(
                budget_reservations.c.ledger_id,
                budget_reservations.c.state,
            ).where(
                budget_reservations.c.invocation_id == invocation.invocation_id,
            )
            if connection.dialect.name == "postgresql":
                reservation_query = reservation_query.with_for_update()
            settled_reservation = next(
                (
                    row["ledger_id"]
                    for row in connection.execute(reservation_query).mappings()
                    if row["state"] != "reserved"
                ),
                None,
            )
            if settled_reservation is not None:
                raise ValueError(
                    "invocation cannot dispatch after its reservation was settled"
                )
            connection.execute(
                update(invocation_records)
                .where(invocation_records.c.id == invocation.invocation_id)
                .values(
                    dispatch_started_at=observed_at,
                    side_effect_state="possible",
                    updated_at=observed_at,
                )
            )
        return self.get(invocation.invocation_id)

    def observe_provider_request(
        self,
        invocation: InvocationRecord,
        provider_request_id: str,
        *,
        now: datetime | None = None,
    ) -> InvocationRecord:
        if not provider_request_id.strip():
            raise ValueError("provider request identity must be non-empty")
        observed_at = _utc(now or _now())
        duplicate = False
        with self.repository.transaction(immediate=True) as connection:
            current = self._locked(connection, invocation)
            if current["provider_result_digest"] is not None:
                raise ValueError(
                    "provider request identity must be observed before terminal result admission"
                )
            self._lock_cross_invocation_identity(
                connection,
                domain="provider-request-v1",
                identity={
                    "provider": str(current["provider"]),
                    "provider_request_id": provider_request_id,
                },
            )
            legacy_namespace = _legacy_provider_request_namespace(
                str(current["provider"])
            )
            if current["provider_request_namespace"] == legacy_namespace:
                # An unpinned or migrated invocation cannot safely distinguish
                # endpoints, so preserve the older provider-wide collision rule.
                namespace_scope = (
                    invocation_records.c.provider == current["provider"]
                )
            else:
                # Pinned endpoints compare within their namespace while still
                # colliding with legacy provider-only evidence whose endpoint
                # identity was never captured.
                namespace_scope = or_(
                    invocation_records.c.provider_request_namespace
                    == current["provider_request_namespace"],
                    invocation_records.c.provider_request_namespace
                    == legacy_namespace,
                )
            matches = connection.execute(
                select(invocation_records.c.id).where(
                    namespace_scope,
                    invocation_records.c.provider_request_id == provider_request_id,
                    invocation_records.c.id != invocation.invocation_id,
                )
            ).scalars().all()
            if matches:
                duplicate = True
                connection.execute(
                    update(invocation_records)
                    .where(invocation_records.c.id.in_((*matches, invocation.invocation_id)))
                    .values(side_effect_state="ambiguous", updated_at=observed_at)
                )
                connection.execute(
                    update(invocation_records)
                    .where(invocation_records.c.id == invocation.invocation_id)
                    .values(
                        provider_request_id=provider_request_id,
                        admission_state="duplicate",
                        updated_at=observed_at,
                    )
                )
            else:
                connection.execute(
                    update(invocation_records)
                    .where(invocation_records.c.id == invocation.invocation_id)
                    .values(
                        provider_request_id=provider_request_id,
                        side_effect_state="observed",
                        updated_at=observed_at,
                    )
                )
        if duplicate:
            raise DuplicateProviderRequest(
                "provider request identity was observed in more than one compatible request namespace"
            )
        return self.get(invocation.invocation_id)

    def admit_terminal(
        self,
        invocation: InvocationRecord,
        *,
        result_digest: str,
        terminal_outcome: str,
        usage_state: UsageState,
        now: datetime | None = None,
    ) -> bool:
        if len(result_digest) != 64 or any(
            character not in "0123456789abcdef" for character in result_digest
        ):
            raise ValueError("result_digest must be a lowercase SHA-256 digest")
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            current = self._locked(connection, invocation, require_current=False)
            self._lock_cross_invocation_identity(
                connection,
                domain="provider-result-v1",
                identity={"provider_result_digest": result_digest},
            )
            # A transport retry may repeat a terminal callback, but it must not
            # mutate the already admitted external result or turn one provider
            # effect into two accounting decisions.
            if current["provider_result_digest"] is not None:
                return False
            duplicate_ids = connection.execute(
                select(invocation_records.c.id).where(
                    invocation_records.c.provider_result_digest == result_digest,
                    invocation_records.c.id != invocation.invocation_id,
                )
            ).scalars().all()
            if duplicate_ids:
                # The first durable owner remains the only admitted external
                # result. Record the conflicting callback as ambiguous without
                # assigning its digest or terminal outcome a second time.
                connection.execute(
                    update(invocation_records)
                    .where(
                        invocation_records.c.id.in_(
                            (*duplicate_ids, invocation.invocation_id)
                        )
                    )
                    .values(side_effect_state="ambiguous", updated_at=observed_at)
                )
                connection.execute(
                    update(invocation_records)
                    .where(invocation_records.c.id == invocation.invocation_id)
                    .values(
                        admission_state=(
                            "duplicate"
                            if current["admission_state"] == "current"
                            else current["admission_state"]
                        ),
                        usage_state=(
                            usage_state if usage_state != "reconciled" else "unknown"
                        ),
                        updated_at=observed_at,
                    )
                )
                return False
            job = connection.execute(
                select(
                    jobs.c.status,
                    jobs.c.lease_owner,
                    jobs.c.lease_expires_at,
                    jobs.c.attempt_count,
                ).where(jobs.c.id == current["job_id"])
            ).first()
            live = (
                current["admission_state"] == "current"
                and job is not None
                and job.status == "running"
                and job.lease_owner == current["lease_owner"]
                and int(job.attempt_count or 0) == int(current["generation"])
                and job.lease_expires_at is not None
                and _utc(job.lease_expires_at) > observed_at
            )
            if not live:
                connection.execute(
                    update(invocation_records)
                    .where(invocation_records.c.id == invocation.invocation_id)
                    .values(
                        admission_state=(
                            current["admission_state"]
                            if current["admission_state"] == "duplicate"
                            else "stale"
                        ),
                        side_effect_state="ambiguous",
                        usage_state=(
                            usage_state if usage_state != "reconciled" else "unknown"
                        ),
                        provider_result_digest=result_digest,
                        terminal_outcome=terminal_outcome,
                        terminal_at=observed_at,
                        updated_at=observed_at,
                    )
                )
                return False
            side_effect_state = (
                "reconciled"
                if usage_state == "reconciled"
                else "ambiguous"
                if usage_state in {"unknown", "disputed"}
                else "observed"
            )
            connection.execute(
                update(invocation_records)
                .where(invocation_records.c.id == invocation.invocation_id)
                .values(
                    provider_result_digest=result_digest,
                    terminal_outcome=terminal_outcome,
                    usage_state=usage_state,
                    side_effect_state=side_effect_state,
                    terminal_at=observed_at,
                    updated_at=observed_at,
                )
            )
        return True

    def request_cancel(self, invocation: InvocationRecord) -> InvocationRecord:
        return self._cancel_transition(invocation, "requested")

    def mark_cancel_dispatched(self, invocation: InvocationRecord) -> InvocationRecord:
        return self._cancel_transition(invocation, "dispatched")

    def mark_cancel_acknowledged(self, invocation: InvocationRecord) -> InvocationRecord:
        return self._cancel_transition(invocation, "acknowledged")

    def mark_cancel_unsupported(self, invocation: InvocationRecord) -> InvocationRecord:
        return self._cancel_transition(invocation, "unsupported")

    def mark_cancel_unknown(self, invocation: InvocationRecord) -> InvocationRecord:
        return self._cancel_transition(invocation, "unknown")

    def mark_lease_lost(
        self,
        invocation: InvocationRecord,
        *,
        now: datetime | None = None,
    ) -> InvocationRecord:
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            current = self._locked(connection, invocation, require_current=False)
            connection.execute(
                update(invocation_records)
                .where(invocation_records.c.id == invocation.invocation_id)
                .values(
                    admission_state=(
                        current["admission_state"]
                        if current["admission_state"] == "duplicate"
                        else "stale"
                    ),
                    side_effect_state=(
                        "not_started"
                        if current["side_effect_state"] == "not_started"
                        else "ambiguous"
                    ),
                    updated_at=observed_at,
                )
            )
        return self.get(invocation.invocation_id)

    def get(self, invocation_id: str) -> InvocationRecord:
        with self.repository.engine.connect() as connection:
            row = connection.execute(
                select(invocation_records).where(invocation_records.c.id == invocation_id)
            ).mappings().first()
        if row is None:
            raise KeyError(invocation_id)
        return self._record(row)

    def current_for_attempt(self, attempt_id: str) -> InvocationRecord | None:
        with self.repository.engine.connect() as connection:
            row = connection.execute(
                select(invocation_records)
                .where(
                    invocation_records.c.attempt_id == attempt_id,
                    invocation_records.c.admission_state == "current",
                )
                .order_by(invocation_records.c.generation.desc())
            ).mappings().first()
        return self._record(row) if row is not None else None

    def list_for_attempt(self, attempt_id: str) -> tuple[InvocationRecord, ...]:
        with self.repository.engine.connect() as connection:
            rows = connection.execute(
                select(invocation_records)
                .where(invocation_records.c.attempt_id == attempt_id)
                .order_by(invocation_records.c.generation)
            ).mappings().all()
        return tuple(self._record(row) for row in rows)

    def _cancel_transition(
        self,
        invocation: InvocationRecord,
        state: CancellationState,
    ) -> InvocationRecord:
        observed_at = _now()
        with self.repository.transaction(immediate=True) as connection:
            current = self._locked(connection, invocation, require_current=False)
            current_state = str(current["cancellation_state"])
            if _CANCEL_RANK[state] < _CANCEL_RANK[current_state]:
                raise ValueError("cancellation state cannot move backwards")
            if _CANCEL_RANK[state] == _CANCEL_RANK[current_state] and state != current_state:
                raise ValueError("terminal cancellation state cannot be replaced")
            connection.execute(
                update(invocation_records)
                .where(invocation_records.c.id == invocation.invocation_id)
                .values(cancellation_state=state, updated_at=observed_at)
            )
        return self.get(invocation.invocation_id)

    def _update_current(
        self,
        invocation: InvocationRecord,
        *,
        values: dict[str, object],
        allowed_side_effects: set[str] | None = None,
    ) -> None:
        with self.repository.transaction(immediate=True) as connection:
            current = self._locked(connection, invocation)
            if (
                allowed_side_effects is not None
                and current["side_effect_state"] not in allowed_side_effects
            ):
                raise ValueError("invocation side-effect state cannot move backwards")
            connection.execute(
                update(invocation_records)
                .where(invocation_records.c.id == invocation.invocation_id)
                .values(**values)
            )

    @staticmethod
    def _locked(connection, invocation: InvocationRecord, *, require_current: bool = True):
        query = select(invocation_records).where(
            invocation_records.c.id == invocation.invocation_id,
            invocation_records.c.fence_token == invocation.fence_token,
        )
        if connection.dialect.name == "postgresql":
            query = query.with_for_update()
        row = connection.execute(query).mappings().first()
        if row is None:
            raise ValueError("invocation fence token does not match durable state")
        if require_current and row["admission_state"] != "current":
            raise ValueError("invocation is no longer the current generation")
        return row

    @staticmethod
    def _lock_cross_invocation_identity(
        connection,
        *,
        domain: str,
        identity: object,
    ) -> None:
        """Serialize cross-row admission on PostgreSQL; SQLite is immediate."""

        if connection.dialect.name != "postgresql":
            return
        connection.execute(
            select(
                func.pg_advisory_xact_lock(
                    cast(_advisory_lock_key(domain=domain, identity=identity), BigInteger)
                )
            )
        )

    @staticmethod
    def _record(row) -> InvocationRecord:
        return InvocationRecord(
            invocation_id=str(row["id"]),
            execution_id=str(row["execution_id"]),
            attempt_id=str(row["attempt_id"]),
            job_id=str(row["job_id"]),
            generation=int(row["generation"]),
            fence_token=str(row["fence_token"]),
            provider=str(row["provider"]),
            provider_model=str(row["provider_model"]),
            provider_idempotency_key=str(row["provider_idempotency_key"]),
            provider_request_namespace=str(row["provider_request_namespace"]),
            provider_request_id=row["provider_request_id"],
            lease_owner=str(row["lease_owner"]),
            lease_acquired_at=_utc(row["lease_acquired_at"]),
            lease_expires_at=_utc(row["lease_expires_at"]),
            dispatch_started_at=(
                _utc(row["dispatch_started_at"])
                if row["dispatch_started_at"] is not None
                else None
            ),
            aggregate_deadline_at=(
                _utc(row["aggregate_deadline_at"])
                if row["aggregate_deadline_at"] is not None
                else None
            ),
            transport_context_state=str(row["transport_context_state"]),
            cancellation_state=row["cancellation_state"],
            side_effect_state=row["side_effect_state"],
            usage_state=row["usage_state"],
            admission_state=row["admission_state"],
            provider_result_digest=row["provider_result_digest"],
            terminal_outcome=row["terminal_outcome"],
            terminal_at=(
                _utc(row["terminal_at"])
                if row["terminal_at"] is not None
                else None
            ),
        )
