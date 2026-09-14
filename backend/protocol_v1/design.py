"""Deterministic treatment generation for declared experimental designs."""

from __future__ import annotations

from itertools import product

from .canonical import sha256
from .models import ExperimentSpec, FactorSpec


def _valid_assignment(assignment: dict[str, str | int | bool], factors: tuple[FactorSpec, ...]) -> bool:
    by_id = {factor.factor_id: factor for factor in factors}
    for factor in factors:
        if assignment[factor.factor_id] == factor.baseline_value:
            continue
        for incompatible_id in factor.incompatible_with:
            other = by_id[incompatible_id]
            if assignment[incompatible_id] != other.baseline_value:
                return False
        for combination in factor.incompatible_level_combinations:
            if all(assignment[factor_id] == value for factor_id, value in combination.assignments.items()):
                return False
    return True


def fractional_design_metadata(experiment: ExperimentSpec) -> dict[str, str | int]:
    """Describe the supported regular two-level half-fraction, without optimality claims."""
    factors = tuple(sorted(experiment.factors, key=lambda item: item.factor_id))
    if experiment.design != "fractional":
        raise ValueError("fractional design metadata is only available for fractional designs")
    if len(factors) < 2 or any(factor.kind != "binary" for factor in factors):
        raise ValueError("fractional designs require at least two binary factors; use custom for other matrices")
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    generator = "".join(letters[index] for index in range(len(factors)))
    return {
        "family": "regular_two_level_half_fraction",
        "generator": f"I={generator}",
        "resolution": len(factors),
        "runs": 2 ** (len(factors) - 1),
    }


def _custom_assignments(experiment: ExperimentSpec) -> list[dict[str, str | int | bool]]:
    factor_ids = {factor.factor_id for factor in experiment.factors}
    levels = {factor.factor_id: set(factor.levels) for factor in experiment.factors}
    assignments: list[dict[str, str | int | bool]] = []
    for treatment in experiment.custom_design:
        assignment = dict(treatment.assignments)
        if set(assignment) != factor_ids:
            raise ValueError("custom treatment must assign every factor exactly once")
        if any(value not in levels[factor_id] for factor_id, value in assignment.items()):
            raise ValueError("custom treatment contains an undeclared factor level")
        assignments.append(assignment)
    return assignments


def expand_design(experiment: ExperimentSpec) -> tuple[dict[str, str | int | bool], ...]:
    """Expand full, deterministic fractional, or custom treatment arms."""
    factors = tuple(sorted(experiment.factors, key=lambda item: item.factor_id))
    if experiment.design == "custom":
        candidates = _custom_assignments(experiment)
    else:
        if experiment.design == "fractional":
            fractional_design_metadata(experiment)
        candidates = [
            dict(zip((factor.factor_id for factor in factors), values, strict=True))
            for values in product(*(factor.levels for factor in factors))
        ]
        if experiment.design == "fractional":
            # Defining relation I=AB... selects the +1 parity half. For four
            # binary factors this is the balanced Resolution IV 2^(4-1) design.
            candidates = [
                assignment
                for assignment in candidates
                if sum(assignment[factor.factor_id] == factor.baseline_value for factor in factors) % 2 == 0
            ]
    valid = [candidate for candidate in candidates if _valid_assignment(candidate, factors)]
    if not valid:
        raise ValueError("design has no valid treatment arms after incompatibilities")
    keys = [sha256(assignment) for assignment in valid]
    if len(set(keys)) != len(keys):
        raise ValueError("design contains duplicate treatment assignments")
    return tuple(valid)


def treatment_id(assignment: dict[str, str | int | bool]) -> str:
    return f"t-{sha256(assignment)[:16]}"
