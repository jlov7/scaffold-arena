"""Deterministic composition for the four bounded flagship mechanisms."""

from __future__ import annotations

from itertools import product
from typing import cast

from protocol_v1.canonical import canonical_configuration_hash, sha256
from protocol_v1.models import (
    CapabilityRequirement,
    FactorSpec,
    ManipulationCheck,
    ShamTreatment,
    TreatmentMutation,
)

from .models import (
    CapabilityProfile,
    CompiledMechanism,
    CompiledRecipe,
    FactorId,
    TreatmentBudget,
)


class RecipeCompilationError(ValueError):
    """The declaration cannot be truthfully represented by this runtime."""


FLAGSHIP_FACTOR_IDS: tuple[FactorId, ...] = ("planning", "verification", "recovery", "memory")
_SHORT_FACTOR_IDS = {"p": "planning", "v": "verification", "r": "recovery", "m": "memory"}


def _factor(
    factor_id: FactorId, description: str, mutation_target: str, capability: str, *, compute: int, context: int
) -> FactorSpec:
    return FactorSpec(
        factor_id=factor_id,
        kind="binary",
        levels=(False, True),
        baseline=False,
        description=description,
        treatment_mutations=(TreatmentMutation(target=mutation_target, operation="enable", level=True),),
        declarative_config={"mechanism": factor_id, "compute_units": compute, "context_bytes": context},
        fixed_infrastructure={"runtime": "factors_v1", "runtime_state": "not_run"},
        prohibited_co_mutations=("provider", "model", "sampling", "task_prompt", "evaluator"),
        manipulation_checks=(ManipulationCheck(factor_id=factor_id, expected_value=True, oracle=f"{factor_id}-delivery"),),
        sham_treatment=ShamTreatment(
            label=f"{factor_id}-matched-sham",
            description="Compute/context-matched sham; it establishes delivery only, not outcome causality.",
            levels=(False,),
        ),
        capability_requirements=(CapabilityRequirement(capability=capability, required=True),),
    )


FLAGSHIP_FACTORS: tuple[FactorSpec, ...] = (
    _factor("planning", "Explicit plan artifact with validated transitions.", "planning", "state", compute=2, context=1_024),
    _factor("verification", "Agent-side evidence-linked pre-finalization verification.", "verification", "state", compute=2, context=1_024),
    _factor("recovery", "Declared-transient checkpoint recovery controls.", "recovery", "checkpoint", compute=2, context=1_024),
    _factor("memory", "Bounded within-episode sourced memory.", "memory", "memory", compute=2, context=1_024),
)


CAPABLE_RECORDED_PROFILE = CapabilityProfile(
    profile_id="recorded-capable-v1",
    adapter_kind="recorded",
    capabilities={"state": True, "checkpoint": True, "memory": True},
)
CAPABLE_NATIVE_PROFILE = CapabilityProfile(
    profile_id="native-capable-v1",
    adapter_kind="native",
    capabilities={"state": True, "checkpoint": True, "memory": True},
)


def _by_id(factors: tuple[FactorSpec, ...]) -> dict[FactorId, FactorSpec]:
    if len(factors) != 4:
        raise RecipeCompilationError("the flagship runtime requires exactly P/V/R/M factor declarations")
    result: dict[FactorId, FactorSpec] = {}
    for factor in factors:
        if factor.factor_id not in FLAGSHIP_FACTOR_IDS or factor.factor_id in result:
            raise RecipeCompilationError("factor declarations must be exactly planning, verification, recovery, memory")
        if factor.kind != "binary" or tuple(factor.levels) != (False, True) or factor.baseline_value is not False:
            raise RecipeCompilationError(f"{factor.factor_id} must be a false/true binary factor with false baseline")
        result[cast(FactorId, factor.factor_id)] = factor
    return result


def _assert_capabilities(factor: FactorSpec, profile: CapabilityProfile) -> tuple[str, ...]:
    required = tuple(item.capability for item in factor.capability_requirements if item.required)
    unavailable = tuple(name for name in required if not getattr(profile.capabilities, name, False))
    if unavailable:
        raise RecipeCompilationError(f"{factor.factor_id} requires unavailable capabilities: {', '.join(unavailable)}")
    return required


def _assert_no_conflicting_mutations(factors: dict[FactorId, FactorSpec], assignment: dict[FactorId, bool]) -> None:
    active = [factor for key, factor in factors.items() if assignment[key]]
    targets = [mutation.target for factor in active for mutation in factor.treatment_mutations if mutation.level is True]
    if len(targets) != len(set(targets)):
        raise RecipeCompilationError("active factors have conflicting treatment mutation targets")
    prohibited = {target for factor in active for target in factor.prohibited_co_mutations}
    if prohibited.intersection(targets):
        raise RecipeCompilationError("an active factor attempts a prohibited co-mutation")
    fixed: dict[str, str | int | bool] = {}
    for factor in factors.values():
        for key, value in factor.fixed_infrastructure.items():
            if key in fixed and fixed[key] != value:
                raise RecipeCompilationError(f"fixed infrastructure conflict for {key}")
            fixed[key] = value
    for factor_id, factor in factors.items():
        if not assignment[factor_id]:
            continue
        if any(assignment.get(other, False) for other in factor.incompatible_with):
            raise RecipeCompilationError(f"{factor_id} has an incompatible active factor")
        for combination in factor.incompatible_level_combinations:
            if all(assignment.get(key) == value for key, value in combination.assignments.items()):
                raise RecipeCompilationError(f"{factor_id} has an incompatible declared level combination")


def compile_recipe(
    assignment: dict[str, bool],
    *,
    factors: tuple[FactorSpec, ...] = FLAGSHIP_FACTORS,
    profile: CapabilityProfile = CAPABLE_RECORDED_PROFILE,
    treatment_budgets: dict[str, TreatmentBudget] | None = None,
) -> CompiledRecipe:
    """Compile one declarative treatment arm; it intentionally never executes it."""
    specs = _by_id(factors)
    normalized_assignment = {_SHORT_FACTOR_IDS.get(key, key): value for key, value in assignment.items()}
    if set(normalized_assignment) != set(FLAGSHIP_FACTOR_IDS) or any(type(value) is not bool for value in normalized_assignment.values()):
        raise RecipeCompilationError("assignment must set every P/V/R/M factor to a strict boolean")
    typed_assignment: dict[FactorId, bool] = {key: normalized_assignment[key] for key in FLAGSHIP_FACTOR_IDS}
    _assert_no_conflicting_mutations(specs, typed_assignment)
    budget_map = treatment_budgets or {}
    if set(budget_map) - set(FLAGSHIP_FACTOR_IDS):
        raise RecipeCompilationError("treatment budgets reference an unknown factor")

    mechanisms: list[CompiledMechanism] = []
    for factor_id in FLAGSHIP_FACTOR_IDS:
        factor = specs[factor_id]
        required = _assert_capabilities(factor, profile)
        selected = typed_assignment[factor_id]
        declared_budget = TreatmentBudget(
            compute_units=int(factor.declarative_config.get("compute_units", 1)),
            context_bytes=int(factor.declarative_config.get("context_bytes", 0)),
        )
        requested_budget = budget_map.get(factor_id)
        if requested_budget is not None and requested_budget != declared_budget:
            raise RecipeCompilationError("treatment budgets must remain matched to the declared sham envelope")
        budget = declared_budget
        configuration = dict(factor.declarative_config)
        configuration["enabled"] = selected
        configuration["treatment_mode"] = "active" if selected else "sham"
        mechanisms.append(
            CompiledMechanism(
                factor_id=factor_id,
                selected_level=selected,
                mode="active" if selected else "sham",
                configuration=configuration,
                configuration_hash=canonical_configuration_hash(configuration),
                treatment_budget=budget,
                required_capabilities=required,
                fidelity_oracles=tuple(check.oracle for check in factor.manipulation_checks),
            )
        )
    recipe_payload = {"assignment": typed_assignment, "mechanisms": mechanisms, "profile_id": profile.profile_id}
    return CompiledRecipe(
        recipe_id=f"recipe-{sha256(recipe_payload)[:16]}", assignment=typed_assignment,
        mechanisms=tuple(mechanisms), configuration_hash=canonical_configuration_hash(recipe_payload), profile_id=profile.profile_id,
    )


def enumerate_flagship_recipes(
    *, profile: CapabilityProfile = CAPABLE_RECORDED_PROFILE,
    factors: tuple[FactorSpec, ...] = FLAGSHIP_FACTORS,
) -> tuple[CompiledRecipe, ...]:
    """Return all 16 P/V/R/M arms in a stable order after fail-closed compilation."""
    return tuple(
        compile_recipe(dict(zip(FLAGSHIP_FACTOR_IDS, values, strict=True)), profile=profile, factors=factors)
        for values in product((False, True), repeat=4)
    )
