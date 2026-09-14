"""Stable public composition boundary for reservation accounting."""

from ._budget_kernel import (
    AggregateBudgetExceeded,
    BudgetReservationService as _KernelBudgetReservationService,
    CostReconciliation,
)

# ``reservations`` imports this module while it is initializing. It receives
# the immutable conservative ledger kernel as its explicit base; the final
# lifecycle-aware policy is rebound only inside this canonical module.
BudgetReservationService = _KernelBudgetReservationService

from .reservation_policy import BudgetReservationService, ReservationLifecycle

__all__ = [
    "AggregateBudgetExceeded",
    "BudgetReservationService",
    "CostReconciliation",
    "ReservationLifecycle",
]
