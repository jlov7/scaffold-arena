"""Bounded composable P/V/R/M mechanism contracts; no execution integration."""

from .adapter import (
    FactorAdapterError,
    FactorExecutionReport,
    FactorizedHarnessAdapter,
    FactorizedRecipeRouterAdapter,
    FactorRuntime,
    FactorRuntimeSession,
    RecoveryObservation,
)
from .compiler import (
    CAPABLE_NATIVE_PROFILE,
    CAPABLE_RECORDED_PROFILE,
    FLAGSHIP_FACTORS,
    RecipeCompilationError,
    compile_recipe,
    enumerate_flagship_recipes,
)
from .fidelity import check_manipulation_fidelity
from .memory import append_memory, new_episode_memory
from .planning import create_plan, transition_plan_step
from .recovery import authorize_recovery
from .verification import verify_before_finalization

__all__ = [
    "CAPABLE_NATIVE_PROFILE",
    "CAPABLE_RECORDED_PROFILE",
    "FLAGSHIP_FACTORS",
    "FactorAdapterError",
    "FactorExecutionReport",
    "FactorRuntime",
    "FactorRuntimeSession",
    "FactorizedHarnessAdapter",
    "FactorizedRecipeRouterAdapter",
    "RecipeCompilationError",
    "RecoveryObservation",
    "append_memory",
    "authorize_recovery",
    "check_manipulation_fidelity",
    "compile_recipe",
    "create_plan",
    "enumerate_flagship_recipes",
    "new_episode_memory",
    "transition_plan_step",
    "verify_before_finalization",
]
