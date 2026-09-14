"""Conservative cost reservation and evidence-bound reconciliation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import insert, select, update

from adapters_v1.models import ProviderUsage
from persistence_v1 import ArenaRepository
from persistence_v1.schema import executions, usage_ledger

from .currency import currency, currency_equal, currency_exceeds, currency_float


def _id() -> str:
    return uuid.uuid4().hex


def _digest(value: str | None) -> bool:
    return value is not None and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


@dataclass(frozen=True)
class CostReconciliation:
    ledger_id: str
    status: str
    cost_usd: float | None


class BudgetReservationService:
    """The absence of provider evidence is unknown, never a zero-cost claim."""

    def __init__(self, repository: ArenaRepository):
        self.repository = repository

    def reserve(
        self, execution_id: str, attempt_id: str, *, model_id: str, max_cost_usd: float,
        max_tokens: int | None = None, max_tool_calls: int | None = None, ledger_id: str | None = None,
    ) -> str:
        if currency(max_cost_usd) < 0 or (max_tokens is not None and max_tokens < 0) or (max_tool_calls is not None and max_tool_calls < 0):
            raise ValueError("reservation cannot be negative")
        ledger_id = ledger_id or _id()
        with self.repository.transaction() as conn:
            conn.execute(insert(usage_ledger).values(
                id=ledger_id, execution_id=execution_id, attempt_id=attempt_id, model_id=model_id,
                cost_status="reserved", reserved_cost_usd=currency_float(max_cost_usd), estimated_cost_usd=currency_float(max_cost_usd),
                reserved_max_tokens=max_tokens, reserved_max_tool_calls=max_tool_calls, cost_usd=None,
            ))
        return ledger_id

    def reserve_with_aggregate(
        self, execution_id: str, attempt_id: str, *, model_id: str, max_cost_usd: float,
        max_attempts: int | None = None, max_total_cost_usd: float | None = None,
        max_tokens: int | None = None, max_tool_calls: int | None = None,
        max_total_tokens: int | None = None, max_total_tool_calls: int | None = None,
        ledger_id: str | None = None,
    ) -> str:
        """Atomically prevent additional starts that exceed count or reserved cost."""
        if (
            currency(max_cost_usd) < 0 or (max_attempts is not None and max_attempts < 1)
            or (max_total_cost_usd is not None and currency(max_total_cost_usd) < 0)
            or (max_tokens is not None and max_tokens < 0) or (max_tool_calls is not None and max_tool_calls < 0)
            or (max_total_tokens is not None and max_total_tokens < 0)
            or (max_total_tool_calls is not None and max_total_tool_calls < 0)
        ):
            raise ValueError("invalid aggregate reservation budget")
        ledger_id = ledger_id or _id()
        with self.repository.transaction(immediate=True) as conn:
            execution_lock = select(executions.c.id).where(executions.c.id == execution_id)
            if self.repository.engine.dialect.name == "postgresql":
                execution_lock = execution_lock.with_for_update()
            if conn.execute(execution_lock).scalar_one_or_none() is None:
                raise KeyError(execution_id)
            prior = conn.execute(select(
                usage_ledger.c.actual_cost_usd, usage_ledger.c.reserved_cost_usd,
                usage_ledger.c.total_tokens, usage_ledger.c.reserved_max_tokens,
                usage_ledger.c.tool_calls, usage_ledger.c.reserved_max_tool_calls,
            ).where(usage_ledger.c.execution_id == execution_id)).mappings().all()
            prior_cost = sum((currency(row["actual_cost_usd"] if row["actual_cost_usd"] is not None else row["reserved_cost_usd"] or 0) for row in prior), currency(0))
            prior_tokens = sum(int(row["total_tokens"] if row["total_tokens"] is not None else row["reserved_max_tokens"] or 0) for row in prior)
            prior_tool_calls = sum(int(row["tool_calls"] if row["tool_calls"] is not None else row["reserved_max_tool_calls"] or 0) for row in prior)
            if max_attempts is not None and len(prior) >= max_attempts:
                raise AggregateBudgetExceeded("aggregate attempt budget would be exceeded")
            if max_total_cost_usd is not None and currency_exceeds(prior_cost + currency(max_cost_usd), max_total_cost_usd):
                raise AggregateBudgetExceeded("aggregate cost reservation would be exceeded")
            if max_total_tokens is not None and prior_tokens + (max_tokens or 0) > max_total_tokens:
                raise AggregateBudgetExceeded("aggregate token reservation would be exceeded")
            if max_total_tool_calls is not None and prior_tool_calls + (max_tool_calls or 0) > max_total_tool_calls:
                raise AggregateBudgetExceeded("aggregate tool-call reservation would be exceeded")
            conn.execute(insert(usage_ledger).values(
                id=ledger_id, execution_id=execution_id, attempt_id=attempt_id, model_id=model_id,
                cost_status="reserved", reserved_cost_usd=currency_float(max_cost_usd), estimated_cost_usd=currency_float(max_cost_usd),
                reserved_max_tokens=max_tokens, reserved_max_tool_calls=max_tool_calls, cost_usd=None,
            ))
        return ledger_id

    def unknown(self, ledger_id: str, *, usage: ProviderUsage | None = None) -> CostReconciliation:
        with self.repository.transaction() as conn:
            result = conn.execute(update(usage_ledger).where(usage_ledger.c.id == ledger_id).values(
                **self._usage_values(usage), cost_status="unknown",
                cost_usd=None, actual_cost_usd=None, price_catalog_revision=None, provider_usage_digest=None,
            ))
        if result.rowcount != 1:
            raise KeyError(ledger_id)
        return CostReconciliation(ledger_id, "unknown", None)

    def mismatch(self, ledger_id: str, *, usage: ProviderUsage | None = None) -> CostReconciliation:
        with self.repository.transaction() as conn:
            result = conn.execute(update(usage_ledger).where(usage_ledger.c.id == ledger_id).values(
                **self._usage_values(usage), cost_status="mismatch",
                cost_usd=None, actual_cost_usd=None, price_catalog_revision=None, provider_usage_digest=None,
            ))
        if result.rowcount != 1:
            raise KeyError(ledger_id)
        return CostReconciliation(ledger_id, "mismatch", None)

    def reconcile(
        self, ledger_id: str, *, input_tokens: int | None, output_tokens: int | None,
        actual_cost_usd: float | None, provider_usage_digest: str | None,
        price_catalog_revision: str | None, expected_cost_usd: float | None = None,
        usage: ProviderUsage | None = None,
    ) -> CostReconciliation:
        if (input_tokens is not None and input_tokens < 0) or (output_tokens is not None and output_tokens < 0) or (actual_cost_usd is not None and currency(actual_cost_usd) < 0):
            raise ValueError("usage and costs cannot be negative")
        valid = (
            actual_cost_usd is not None and _digest(provider_usage_digest) and bool(price_catalog_revision)
            and usage is not None and usage.complete_usage
        )
        mismatch = not valid or (expected_cost_usd is not None and not currency_equal(actual_cost_usd, expected_cost_usd))
        status = "mismatch" if mismatch else "reconciled"
        cost = None if mismatch else actual_cost_usd
        with self.repository.transaction() as conn:
            values = {
                **self._usage_values(usage, input_tokens=input_tokens, output_tokens=output_tokens), "cost_status": status,
                "cost_usd": currency_float(cost) if cost is not None else None,
                "actual_cost_usd": currency_float(cost) if cost is not None else None,
                "provider_usage_digest": provider_usage_digest if _digest(provider_usage_digest) else None,
                "price_catalog_revision": price_catalog_revision if valid else None,
            }
            result = conn.execute(update(usage_ledger).where(usage_ledger.c.id == ledger_id).values(**values))
        if result.rowcount != 1:
            raise KeyError(ledger_id)
        return CostReconciliation(ledger_id, status, currency_float(cost) if cost is not None else None)

    def latest_for_attempt(self, attempt_id: str) -> dict[str, object] | None:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(usage_ledger).where(usage_ledger.c.attempt_id == attempt_id).order_by(usage_ledger.c.created_at.desc())).mappings().first()
        return dict(row) if row else None

    @staticmethod
    def _usage_values(
        usage: ProviderUsage | None, *, input_tokens: int | None = None, output_tokens: int | None = None,
    ) -> dict[str, int | None]:
        return {
            "input_tokens": input_tokens if usage is None else usage.input_tokens,
            "output_tokens": output_tokens if usage is None else usage.output_tokens,
            "total_tokens": usage.total_tokens if usage is not None else None,
            "context_tokens": usage.context_tokens if usage is not None else None,
            "tool_calls": usage.tool_calls if usage is not None else None,
        }


class AggregateBudgetExceeded(ValueError):
    pass
