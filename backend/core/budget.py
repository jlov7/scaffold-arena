from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import date
from threading import Lock


class BudgetExceededError(RuntimeError):
    pass


class DailyBudgetExceededError(BudgetExceededError):
    pass


class RunBudgetExceededError(BudgetExceededError):
    pass


_current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)


def set_current_run_id(run_id: str) -> Token:
    return _current_run_id.set(run_id)


def reset_current_run_id(token: Token) -> None:
    _current_run_id.reset(token)


def get_current_run_id() -> str | None:
    return _current_run_id.get()


class BudgetTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._day = date.today().isoformat()
        self._daily_spend_usd = 0.0
        self._run_spend_usd: dict[str, float] = {}

    def _rollover_if_needed_locked(self) -> None:
        today = date.today().isoformat()
        if today != self._day:
            self._day = today
            self._daily_spend_usd = 0.0
            self._run_spend_usd.clear()

    def check_new_run_allowed(self, *, daily_budget_usd: float) -> None:
        with self._lock:
            self._rollover_if_needed_locked()
            if self._daily_spend_usd >= daily_budget_usd:
                raise DailyBudgetExceededError(
                    f"Daily budget exhausted (${self._daily_spend_usd:.4f}/${daily_budget_usd:.4f})"
                )

    def check_call_allowed(
        self,
        *,
        run_id: str,
        max_cost_per_run_usd: float,
        daily_budget_usd: float,
    ) -> None:
        with self._lock:
            self._rollover_if_needed_locked()
            run_spend = self._run_spend_usd.get(run_id, 0.0)
            if run_spend >= max_cost_per_run_usd:
                raise RunBudgetExceededError(
                    f"Run budget exceeded (${run_spend:.4f}/${max_cost_per_run_usd:.4f})"
                )
            if self._daily_spend_usd >= daily_budget_usd:
                raise DailyBudgetExceededError(
                    f"Daily budget exhausted (${self._daily_spend_usd:.4f}/${daily_budget_usd:.4f})"
                )

    def record_spend(self, *, run_id: str, cost_usd: float) -> None:
        if cost_usd <= 0:
            return
        with self._lock:
            self._rollover_if_needed_locked()
            self._daily_spend_usd += cost_usd
            self._run_spend_usd[run_id] = self._run_spend_usd.get(run_id, 0.0) + cost_usd

    def close_run(self, run_id: str) -> None:
        with self._lock:
            self._run_spend_usd.pop(run_id, None)

    def snapshot(self, *, daily_budget_usd: float) -> dict:
        with self._lock:
            self._rollover_if_needed_locked()
            remaining = max(0.0, daily_budget_usd - self._daily_spend_usd)
            return {
                "day": self._day,
                "daily_spent_usd": round(self._daily_spend_usd, 6),
                "daily_budget_usd": round(daily_budget_usd, 6),
                "daily_remaining_usd": round(remaining, 6),
            }


budget_tracker = BudgetTracker()
