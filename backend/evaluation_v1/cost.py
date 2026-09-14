"""Conservative cost-status derivation for immutable protocol-v1 evaluations."""

from __future__ import annotations

import math
from typing import Literal

CostOutcomeStatus = Literal["within_budget", "over_budget", "unknown"]


def reconciled_cost_status(
    reconciled_cost_usd: float | None, budget_limit_usd: float | None
) -> CostOutcomeStatus:
    """Classify only a reconciled cost against a recovered immutable budget limit."""
    valid = lambda value: (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
    if not valid(reconciled_cost_usd) or not valid(budget_limit_usd):
        return "unknown"
    return "within_budget" if reconciled_cost_usd <= budget_limit_usd else "over_budget"
