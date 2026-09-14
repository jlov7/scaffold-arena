"""Deterministic currency policy for provider reconciliation.

Provider amounts are parsed from their decimal string representation and rounded
half-even to one billionth of a USD before comparison, aggregation, or storage.
Differences smaller than half a nanodollar are intentionally equivalent; this
avoids binary-float artifacts such as ``0.1 + 0.2`` while preserving token-level
prices below one microdollar.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

CURRENCY_QUANTUM = Decimal("0.000000001")


def currency(value: Decimal | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CURRENCY_QUANTUM, rounding=ROUND_HALF_EVEN)


def currency_float(value: Decimal | float | str) -> float:
    return float(currency(value))


def currency_equal(left: Decimal | float | str, right: Decimal | float | str) -> bool:
    return currency(left) == currency(right)


def currency_exceeds(left: Decimal | float | str, right: Decimal | float | str) -> bool:
    return currency(left) > currency(right)
