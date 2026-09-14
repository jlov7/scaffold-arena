"""Explicit lifecycle for every conservative usage reservation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select, update

from adapters_v1.models import ProviderUsage
from persistence_v1 import ArenaRepository
from persistence_v1.invocation_schema import budget_reservations, invocation_records
from persistence_v1.schema import executions, jobs, usage_ledger

from .budget import (
    AggregateBudgetExceeded,
    BudgetReservationService as _BaseBudgetReservationService,
    CostReconciliation,
)
from .currency import currency, currency_equal, currency_exceeds, currency_float

_TERMINAL_STATES = frozenset(
    {"committed", "released", "expired", "disputed", "unknown_usage"}
)


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _digest(value: str | None) -> bool:
    return value is not None and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


@dataclass(frozen=True)
class ReservationLifecycle:
    reservation_id: str
    ledger_id: str
    execution_id: str
    attempt_id: str | None
    invocation_id: str | None
    state: str
    reason: str | None
    version: int
    reserved_at: datetime
    updated_at: datetime
    terminal_at: datetime | None


class BudgetReservationService(_BaseBudgetReservationService):
    """Reserve conservatively and ensure no row remains indefinitely reserved."""

    def reserve(
        self,
        execution_id: str,
        attempt_id: str,
        *,
        model_id: str,
        max_cost_usd: float,
        max_tokens: int | None = None,
        max_tool_calls: int | None = None,
        ledger_id: str | None = None,
        now: datetime | None = None,
    ) -> str:
        if (
            currency(max_cost_usd) < 0
            or (max_tokens is not None and max_tokens < 0)
            or (max_tool_calls is not None and max_tool_calls < 0)
        ):
            raise ValueError("reservation cannot be negative")
        ledger_id = ledger_id or _id()
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            self._insert_reservation(
                connection,
                ledger_id=ledger_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                model_id=model_id,
                max_cost_usd=max_cost_usd,
                max_tokens=max_tokens,
                max_tool_calls=max_tool_calls,
                observed_at=observed_at,
            )
        return ledger_id

    def reserve_with_aggregate(
        self,
        execution_id: str,
        attempt_id: str,
        *,
        model_id: str,
        max_cost_usd: float,
        max_attempts: int | None = None,
        max_total_cost_usd: float | None = None,
        max_tokens: int | None = None,
        max_tool_calls: int | None = None,
        max_total_tokens: int | None = None,
        max_total_tool_calls: int | None = None,
        ledger_id: str | None = None,
        now: datetime | None = None,
    ) -> str:
        if (
            currency(max_cost_usd) < 0
            or (max_attempts is not None and max_attempts < 1)
            or (
                max_total_cost_usd is not None
                and currency(max_total_cost_usd) < 0
            )
            or (max_tokens is not None and max_tokens < 0)
            or (max_tool_calls is not None and max_tool_calls < 0)
            or (max_total_tokens is not None and max_total_tokens < 0)
            or (max_total_tool_calls is not None and max_total_tool_calls < 0)
        ):
            raise ValueError("invalid aggregate reservation budget")
        ledger_id = ledger_id or _id()
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            execution_lock = select(executions.c.id).where(
                executions.c.id == execution_id
            )
            if self.repository.engine.dialect.name == "postgresql":
                execution_lock = execution_lock.with_for_update()
            if connection.execute(execution_lock).scalar_one_or_none() is None:
                raise KeyError(execution_id)

            prior = connection.execute(
                select(
                    usage_ledger.c.actual_cost_usd,
                    usage_ledger.c.reserved_cost_usd,
                    usage_ledger.c.total_tokens,
                    usage_ledger.c.reserved_max_tokens,
                    usage_ledger.c.tool_calls,
                    usage_ledger.c.reserved_max_tool_calls,
                    budget_reservations.c.state.label("reservation_state"),
                )
                .select_from(
                    usage_ledger.outerjoin(
                        budget_reservations,
                        budget_reservations.c.ledger_id == usage_ledger.c.id,
                    )
                )
                .where(usage_ledger.c.execution_id == execution_id)
            ).mappings().all()
            active = [
                row
                for row in prior
                if row["reservation_state"] not in {"released", "expired"}
            ]
            prior_cost = sum(
                (
                    currency(
                        row["actual_cost_usd"]
                        if row["actual_cost_usd"] is not None
                        else row["reserved_cost_usd"] or 0
                    )
                    for row in active
                ),
                currency(0),
            )
            prior_tokens = sum(
                int(
                    row["total_tokens"]
                    if row["total_tokens"] is not None
                    else row["reserved_max_tokens"] or 0
                )
                for row in active
            )
            prior_tool_calls = sum(
                int(
                    row["tool_calls"]
                    if row["tool_calls"] is not None
                    else row["reserved_max_tool_calls"] or 0
                )
                for row in active
            )
            if max_attempts is not None and len(active) >= max_attempts:
                raise AggregateBudgetExceeded(
                    "aggregate attempt budget would be exceeded"
                )
            if max_total_cost_usd is not None and currency_exceeds(
                prior_cost + currency(max_cost_usd), max_total_cost_usd
            ):
                raise AggregateBudgetExceeded(
                    "aggregate cost reservation would be exceeded"
                )
            if (
                max_total_tokens is not None
                and prior_tokens + (max_tokens or 0) > max_total_tokens
            ):
                raise AggregateBudgetExceeded(
                    "aggregate token reservation would be exceeded"
                )
            if (
                max_total_tool_calls is not None
                and prior_tool_calls + (max_tool_calls or 0) > max_total_tool_calls
            ):
                raise AggregateBudgetExceeded(
                    "aggregate tool-call reservation would be exceeded"
                )
            self._insert_reservation(
                connection,
                ledger_id=ledger_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                model_id=model_id,
                max_cost_usd=max_cost_usd,
                max_tokens=max_tokens,
                max_tool_calls=max_tool_calls,
                observed_at=observed_at,
            )
        return ledger_id

    def unknown(
        self,
        ledger_id: str,
        *,
        usage: ProviderUsage | None = None,
        now: datetime | None = None,
    ) -> CostReconciliation:
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            self._require_open(connection, ledger_id)
            result = connection.execute(
                update(usage_ledger)
                .where(usage_ledger.c.id == ledger_id)
                .values(
                    **self._usage_values(usage),
                    cost_status="unknown",
                    cost_usd=None,
                    actual_cost_usd=None,
                    price_catalog_revision=None,
                    provider_usage_digest=None,
                )
            )
            self._transition_in_connection(
                connection,
                ledger_id,
                state="unknown_usage",
                reason="provider usage could not be conclusively reconciled",
                observed_at=observed_at,
            )
        if result.rowcount != 1:
            raise KeyError(ledger_id)
        return CostReconciliation(ledger_id, "unknown", None)

    def mismatch(
        self,
        ledger_id: str,
        *,
        usage: ProviderUsage | None = None,
        now: datetime | None = None,
    ) -> CostReconciliation:
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            self._require_open(connection, ledger_id)
            result = connection.execute(
                update(usage_ledger)
                .where(usage_ledger.c.id == ledger_id)
                .values(
                    **self._usage_values(usage),
                    cost_status="mismatch",
                    cost_usd=None,
                    actual_cost_usd=None,
                    price_catalog_revision=None,
                    provider_usage_digest=None,
                )
            )
            self._transition_in_connection(
                connection,
                ledger_id,
                state="disputed",
                reason="provider usage or pricing evidence did not match",
                observed_at=observed_at,
            )
        if result.rowcount != 1:
            raise KeyError(ledger_id)
        return CostReconciliation(ledger_id, "mismatch", None)

    def reconcile(
        self,
        ledger_id: str,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        actual_cost_usd: float | None,
        provider_usage_digest: str | None,
        price_catalog_revision: str | None,
        expected_cost_usd: float | None = None,
        usage: ProviderUsage | None = None,
        now: datetime | None = None,
    ) -> CostReconciliation:
        if (
            (input_tokens is not None and input_tokens < 0)
            or (output_tokens is not None and output_tokens < 0)
            or (
                actual_cost_usd is not None
                and currency(actual_cost_usd) < 0
            )
        ):
            raise ValueError("usage and costs cannot be negative")
        valid = (
            actual_cost_usd is not None
            and _digest(provider_usage_digest)
            and bool(price_catalog_revision)
            and usage is not None
            and usage.complete_usage
        )
        mismatch = not valid or (
            expected_cost_usd is not None
            and not currency_equal(actual_cost_usd, expected_cost_usd)
        )
        status = "mismatch" if mismatch else "reconciled"
        state = "disputed" if mismatch else "committed"
        cost = None if mismatch else actual_cost_usd
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            self._require_open(connection, ledger_id)
            values = {
                **self._usage_values(
                    usage,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ),
                "cost_status": status,
                "cost_usd": currency_float(cost) if cost is not None else None,
                "actual_cost_usd": (
                    currency_float(cost) if cost is not None else None
                ),
                "provider_usage_digest": (
                    provider_usage_digest if _digest(provider_usage_digest) else None
                ),
                "price_catalog_revision": (
                    price_catalog_revision if valid else None
                ),
            }
            result = connection.execute(
                update(usage_ledger)
                .where(usage_ledger.c.id == ledger_id)
                .values(**values)
            )
            self._transition_in_connection(
                connection,
                ledger_id,
                state=state,
                reason=(
                    "usage and price evidence reconciled"
                    if not mismatch
                    else "usage or price evidence mismatch"
                ),
                observed_at=observed_at,
            )
        if result.rowcount != 1:
            raise KeyError(ledger_id)
        return CostReconciliation(
            ledger_id,
            status,
            currency_float(cost) if cost is not None else None,
        )

    def release(
        self,
        ledger_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> ReservationLifecycle:
        if not reason.strip():
            raise ValueError("release requires a reason")
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            invocation = self._lock_bound_invocation(connection, ledger_id)
            self._require_open(connection, ledger_id)
            if invocation is not None:
                if invocation["side_effect_state"] != "not_started":
                    raise ValueError(
                        "reservation cannot be released after possible provider dispatch"
                    )
            connection.execute(
                update(usage_ledger)
                .where(usage_ledger.c.id == ledger_id)
                .values(
                    cost_status="released",
                    cost_usd=None,
                    actual_cost_usd=None,
                    price_catalog_revision=None,
                    provider_usage_digest=None,
                )
            )
            self._transition_in_connection(
                connection,
                ledger_id,
                state="released",
                reason=reason,
                observed_at=observed_at,
            )
        return self.lifecycle(ledger_id)

    def expire(
        self,
        ledger_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> ReservationLifecycle:
        observed_at = _utc(now or _now())
        with self.repository.transaction(immediate=True) as connection:
            invocation = self._lock_bound_invocation(connection, ledger_id)
            self._require_open(connection, ledger_id)
            if invocation is not None and invocation["side_effect_state"] != "not_started":
                connection.execute(
                    update(usage_ledger)
                    .where(usage_ledger.c.id == ledger_id)
                    .values(
                        cost_status="unknown",
                        cost_usd=None,
                        actual_cost_usd=None,
                        price_catalog_revision=None,
                        provider_usage_digest=None,
                    )
                )
                self._transition_in_connection(
                    connection,
                    ledger_id,
                    state="unknown_usage",
                    reason="reservation reached expiry after possible provider dispatch",
                    observed_at=observed_at,
                )
            else:
                connection.execute(
                    update(usage_ledger)
                    .where(usage_ledger.c.id == ledger_id)
                    .values(
                        cost_status="expired",
                        cost_usd=None,
                        actual_cost_usd=None,
                        price_catalog_revision=None,
                        provider_usage_digest=None,
                    )
                )
                self._transition_in_connection(
                    connection,
                    ledger_id,
                    state="expired",
                    reason=reason,
                    observed_at=observed_at,
                )
        return self.lifecycle(ledger_id)

    def settle_open_for_invocation(
        self,
        invocation_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        observed_at = _utc(now or _now())
        settled: list[str] = []
        with self.repository.transaction(immediate=True) as connection:
            invocation = self._lock_invocation(connection, invocation_id)
            if invocation is None:
                return ()
            rows = connection.execute(
                select(budget_reservations).where(
                    budget_reservations.c.invocation_id == invocation_id,
                    budget_reservations.c.state == "reserved",
                )
            ).mappings().all()
            for row in rows:
                ledger_id = str(row["ledger_id"])
                locked = self._require_open(connection, ledger_id)
                if locked["state"] != "reserved":
                    continue
                if invocation["side_effect_state"] == "not_started":
                    connection.execute(
                        update(usage_ledger)
                        .where(usage_ledger.c.id == ledger_id)
                        .values(cost_status="released")
                    )
                    state = "released"
                else:
                    connection.execute(
                        update(usage_ledger)
                        .where(usage_ledger.c.id == ledger_id)
                        .values(
                            cost_status="unknown",
                            cost_usd=None,
                            actual_cost_usd=None,
                            price_catalog_revision=None,
                            provider_usage_digest=None,
                        )
                    )
                    state = "unknown_usage"
                self._transition_in_connection(
                    connection,
                    ledger_id,
                    state=state,
                    reason=reason,
                    observed_at=observed_at,
                )
                settled.append(ledger_id)
        return tuple(settled)

    def reconcile_stranded(
        self,
        *,
        now: datetime | None = None,
        stale_after_seconds: float = 300.0,
    ) -> tuple[str, ...]:
        if stale_after_seconds < 0:
            raise ValueError("stale_after_seconds cannot be negative")
        observed_at = _utc(now or _now())
        cutoff = observed_at - timedelta(seconds=stale_after_seconds)
        reconciled: list[str] = []
        with self.repository.transaction(immediate=True) as connection:
            rows = connection.execute(
                select(
                    budget_reservations,
                    invocation_records.c.side_effect_state,
                    invocation_records.c.job_id,
                    jobs.c.status.label("job_status"),
                    jobs.c.lease_expires_at,
                )
                .select_from(
                    budget_reservations.outerjoin(
                        invocation_records,
                        budget_reservations.c.invocation_id
                        == invocation_records.c.id,
                    ).outerjoin(jobs, invocation_records.c.job_id == jobs.c.id)
                )
                .where(budget_reservations.c.state == "reserved")
            ).mappings().all()
            for row in rows:
                if _utc(row["reserved_at"]) > cutoff:
                    continue
                live = (
                    row["job_status"] == "running"
                    and row["lease_expires_at"] is not None
                    and _utc(row["lease_expires_at"]) > observed_at
                )
                if live:
                    continue
                ledger_id = str(row["ledger_id"])
                invocation = self._lock_invocation(
                    connection,
                    row["invocation_id"],
                )
                try:
                    locked = self._require_open(connection, ledger_id)
                except ValueError:
                    continue
                if locked["state"] != "reserved":
                    continue
                side_effect_state = (
                    invocation["side_effect_state"] if invocation is not None else None
                )
                if side_effect_state in {None, "not_started"}:
                    connection.execute(
                        update(usage_ledger)
                        .where(usage_ledger.c.id == ledger_id)
                        .values(cost_status="expired")
                    )
                    state = "expired"
                    reason = "reservation expired before any provider dispatch was observed"
                else:
                    connection.execute(
                        update(usage_ledger)
                        .where(usage_ledger.c.id == ledger_id)
                        .values(
                            cost_status="unknown",
                            cost_usd=None,
                            actual_cost_usd=None,
                            price_catalog_revision=None,
                            provider_usage_digest=None,
                        )
                    )
                    state = "unknown_usage"
                    reason = "reservation outlived its lease after possible provider dispatch"
                self._transition_in_connection(
                    connection,
                    ledger_id,
                    state=state,
                    reason=reason,
                    observed_at=observed_at,
                )
                reconciled.append(ledger_id)
        return tuple(reconciled)

    def lifecycle(self, ledger_id: str) -> ReservationLifecycle:
        with self.repository.engine.connect() as connection:
            row = connection.execute(
                select(budget_reservations).where(
                    budget_reservations.c.ledger_id == ledger_id
                )
            ).mappings().first()
        if row is None:
            raise KeyError(ledger_id)
        return self._lifecycle(row)

    def latest_for_attempt(self, attempt_id: str) -> dict[str, object] | None:
        with self.repository.engine.connect() as connection:
            row = connection.execute(
                select(usage_ledger)
                .where(usage_ledger.c.attempt_id == attempt_id)
                .order_by(usage_ledger.c.created_at.desc())
            ).mappings().first()
        return dict(row) if row else None

    def _insert_reservation(
        self,
        connection,
        *,
        ledger_id: str,
        execution_id: str,
        attempt_id: str,
        model_id: str,
        max_cost_usd: float,
        max_tokens: int | None,
        max_tool_calls: int | None,
        observed_at: datetime,
    ) -> None:
        invocation_id = connection.execute(
            select(invocation_records.c.id)
            .where(
                invocation_records.c.attempt_id == attempt_id,
                invocation_records.c.admission_state == "current",
            )
            .order_by(invocation_records.c.generation.desc())
        ).scalar_one_or_none()
        connection.execute(
            insert(usage_ledger).values(
                id=ledger_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                model_id=model_id,
                cost_status="reserved",
                reserved_cost_usd=currency_float(max_cost_usd),
                estimated_cost_usd=currency_float(max_cost_usd),
                reserved_max_tokens=max_tokens,
                reserved_max_tool_calls=max_tool_calls,
                cost_usd=None,
                created_at=observed_at,
            )
        )
        connection.execute(
            insert(budget_reservations).values(
                id=_id(),
                ledger_id=ledger_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                invocation_id=invocation_id,
                state="reserved",
                version=1,
                reserved_at=observed_at,
                updated_at=observed_at,
            )
        )

    @staticmethod
    def _usage_values(
        usage: ProviderUsage | None,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> dict[str, int | None]:
        return {
            "input_tokens": input_tokens if usage is None else usage.input_tokens,
            "output_tokens": output_tokens if usage is None else usage.output_tokens,
            "total_tokens": usage.total_tokens if usage is not None else None,
            "context_tokens": usage.context_tokens if usage is not None else None,
            "tool_calls": usage.tool_calls if usage is not None else None,
        }

    def _require_open(self, connection, ledger_id: str):
        query = select(budget_reservations).where(
            budget_reservations.c.ledger_id == ledger_id
        )
        if connection.dialect.name == "postgresql":
            query = query.with_for_update()
        row = connection.execute(query).mappings().first()
        if row is None:
            raise KeyError(ledger_id)
        if row["state"] in _TERMINAL_STATES:
            raise ValueError("terminal reservation lifecycle is immutable")
        return row

    def _lock_bound_invocation(self, connection, ledger_id: str):
        invocation_id = connection.execute(
            select(budget_reservations.c.invocation_id).where(
                budget_reservations.c.ledger_id == ledger_id
            )
        ).scalar_one_or_none()
        if invocation_id is None:
            return None
        return self._lock_invocation(connection, str(invocation_id))

    @staticmethod
    def _lock_invocation(connection, invocation_id: str | None):
        if invocation_id is None:
            return None
        query = select(invocation_records).where(
            invocation_records.c.id == invocation_id
        )
        if connection.dialect.name == "postgresql":
            query = query.with_for_update()
        return connection.execute(query).mappings().first()

    def _transition_in_connection(
        self,
        connection,
        ledger_id: str,
        *,
        state: str,
        reason: str,
        observed_at: datetime,
    ) -> None:
        row = connection.execute(
            select(
                budget_reservations.c.state,
                budget_reservations.c.version,
            ).where(budget_reservations.c.ledger_id == ledger_id)
        ).first()
        if row is None:
            raise KeyError(ledger_id)
        if row.state in _TERMINAL_STATES:
            raise ValueError("terminal reservation lifecycle is immutable")
        result = connection.execute(
            update(budget_reservations)
            .where(
                budget_reservations.c.ledger_id == ledger_id,
                budget_reservations.c.version == row.version,
            )
            .values(
                state=state,
                reason=reason,
                version=int(row.version) + 1,
                updated_at=observed_at,
                terminal_at=observed_at if state in _TERMINAL_STATES else None,
            )
        )
        if result.rowcount != 1:
            raise ValueError("reservation transition was superseded")

    @staticmethod
    def _lifecycle(row) -> ReservationLifecycle:
        return ReservationLifecycle(
            reservation_id=str(row["id"]),
            ledger_id=str(row["ledger_id"]),
            execution_id=str(row["execution_id"]),
            attempt_id=row["attempt_id"],
            invocation_id=row["invocation_id"],
            state=str(row["state"]),
            reason=row["reason"],
            version=int(row["version"]),
            reserved_at=_utc(row["reserved_at"]),
            updated_at=_utc(row["updated_at"]),
            terminal_at=(
                _utc(row["terminal_at"]) if row["terminal_at"] is not None else None
            ),
        )
