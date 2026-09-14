"""Explicit state-transition policy over reservation persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from persistence_v1.invocation_schema import budget_reservations

from .reservations import (
    BudgetReservationService as _LifecycleBudgetReservationService,
    ReservationLifecycle,
)

# Unknown usage and disputed evidence remain unresolved and may receive late
# reconciliation. Only committed, released, or expired reservations are
# immutable. The policy is expressed through explicit method overrides rather
# than changing globals in another imported module.
_SETTLED_STATES = frozenset({"committed", "released", "expired"})


class BudgetReservationService(_LifecycleBudgetReservationService):
    """Permit late evidence without allowing unresolved cost to disappear."""

    def _require_open(self, connection, ledger_id: str):
        query = select(budget_reservations).where(
            budget_reservations.c.ledger_id == ledger_id
        )
        if connection.dialect.name == "postgresql":
            query = query.with_for_update()
        row = connection.execute(query).mappings().first()
        if row is None:
            raise KeyError(ledger_id)
        if row["state"] in _SETTLED_STATES:
            raise ValueError("terminal reservation lifecycle is immutable")
        return row

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
        if row.state in _SETTLED_STATES:
            raise ValueError("terminal reservation lifecycle is immutable")
        changed = connection.execute(
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
                terminal_at=observed_at if state in _SETTLED_STATES else None,
            )
        )
        if changed.rowcount != 1:
            raise ValueError("reservation lifecycle changed concurrently")

    def release(
        self,
        ledger_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> ReservationLifecycle:
        lifecycle = self.lifecycle(ledger_id)
        if lifecycle.state in _SETTLED_STATES:
            raise ValueError("terminal reservation lifecycle is immutable")
        if lifecycle.state != "reserved":
            raise ValueError(
                "unknown or disputed usage cannot be released without reconciliation"
            )
        return super().release(ledger_id, reason=reason, now=now)

    def expire(
        self,
        ledger_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> ReservationLifecycle:
        lifecycle = self.lifecycle(ledger_id)
        if lifecycle.state in _SETTLED_STATES:
            raise ValueError("terminal reservation lifecycle is immutable")
        if lifecycle.state != "reserved":
            raise ValueError("only a reserved lifecycle can expire")
        return super().expire(ledger_id, reason=reason, now=now)


__all__ = ["BudgetReservationService", "ReservationLifecycle"]
