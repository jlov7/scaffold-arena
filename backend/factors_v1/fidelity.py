"""Treatment-delivery checks.  Passing does not establish causal outcomes."""

from __future__ import annotations

from .models import (
    CompiledRecipe,
    EvidencePointer,
    ManipulationFidelity,
    TreatmentBudget,
)


def check_manipulation_fidelity(
    recipe: CompiledRecipe,
    observed_assignment: dict[str, bool],
    observed_budgets: dict[str, TreatmentBudget],
    evidence: tuple[EvidencePointer, ...],
) -> tuple[ManipulationFidelity, ...]:
    if not evidence:
        raise ValueError("manipulation fidelity requires delivery evidence")
    if set(observed_assignment) != set(recipe.assignment) or any(type(value) is not bool for value in observed_assignment.values()):
        raise ValueError("observed assignment must strictly cover the compiled recipe")
    if set(observed_budgets) != set(recipe.assignment):
        raise ValueError("observed treatment budgets must strictly cover the compiled recipe")
    results: list[ManipulationFidelity] = []
    for mechanism in recipe.mechanisms:
        observed = observed_assignment[mechanism.factor_id]
        matched = observed_budgets[mechanism.factor_id] == mechanism.treatment_budget
        results.append(ManipulationFidelity(
            factor_id=mechanism.factor_id, expected_level=mechanism.selected_level, observed_level=observed,
            mode=mechanism.mode, compute_context_matched=matched, delivered=observed == mechanism.selected_level and matched,
            evidence=evidence,
        ))
    return tuple(results)
