"""Optional, preregistered hierarchical research analysis.

This module never accepts fitted values from callers.  It either fits the
declared model from immutable episode records or returns a typed HOLD.
"""

from __future__ import annotations

import importlib.util
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from protocol_v1.canonical import sha256


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ResearchEffect(ResearchModel):
    term: str
    estimate: float
    credible_interval: tuple[float, float]


class ResearchAnalysisReport(ResearchModel):
    status: Literal[
        "NOT_RUN",
        "RESEARCH_EXTRA_UNAVAILABLE",
        "HOLD_ADEQUACY",
        "HOLD_SEPARATION",
        "HOLD_SINGULAR",
        "HOLD_NONCONVERGED",
        "ESTIMATED",
    ]
    reason: str | None = None
    estimator: str | None = None
    package_versions: tuple[tuple[str, str], ...] = ()
    formula: str | None = None
    random_effects: str | None = None
    converged: bool | None = None
    effects: tuple[ResearchEffect, ...] = ()
    data_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def research_extra_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("statsmodels", "pandas"))


def fit_preregistered_logistic(
    *, attempts: tuple[Any, ...], registered_factors: tuple[Any, ...],
    interactions: tuple[Any, ...], claim_eligible: bool,
) -> ResearchAnalysisReport:
    rows = _rows(attempts, registered_factors)
    digest = sha256(rows)
    if not claim_eligible:
        return ResearchAnalysisReport(status="HOLD_ADEQUACY", reason="research fit requires every adequacy and evidence gate", data_digest=digest)
    if not research_extra_available():
        return ResearchAnalysisReport(status="RESEARCH_EXTRA_UNAVAILABLE", reason="install Scaffold Arena's research optional dependency group", data_digest=digest)
    if len({row["success"] for row in rows}) < 2:
        return ResearchAnalysisReport(status="HOLD_SEPARATION", reason="binary outcome has no variation", data_digest=digest)
    try:
        import numpy as np
        import pandas as pd
        import statsmodels
        from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM

        frame = pd.DataFrame(rows)
        terms = ["C(stressor)"] + [f"C({name})" for name in _factor_columns(registered_factors)]
        for spec in interactions:
            a = _factor_column(spec.factor_a, registered_factors)
            b = _factor_column(spec.factor_b, registered_factors)
            terms.append(f"C({a}):C({b})")
        formula = "success ~ " + " + ".join(terms)
        random_effects = "0 + C(task_cluster)"
        model = BinomialBayesMixedGLM.from_formula(formula, {"task_cluster": random_effects}, frame)
        initial_size = model.k_fep + model.k_vcp + model.k_vc
        result = model.fit_vb(
            mean=np.zeros(initial_size), sd=np.full(initial_size, 0.1),
        )
        converged = bool(getattr(result, "optim_retvals", {}).get("success", False))
        if not converged:
            return ResearchAnalysisReport(status="HOLD_NONCONVERGED", reason="variational optimizer did not converge", estimator="BinomialBayesMixedGLM.fit_vb", package_versions=(("statsmodels", statsmodels.__version__),), formula=formula, random_effects=random_effects, converged=False, data_digest=digest)
        effects = tuple(
            ResearchEffect(
                term=name,
                estimate=float(estimate),
                credible_interval=(float(estimate - 1.96 * sd), float(estimate + 1.96 * sd)),
            )
            for name, estimate, sd in zip(model.exog_names, result.fe_mean, result.fe_sd, strict=True)
            if all(math.isfinite(float(value)) for value in (estimate, sd))
        )
        if not effects:
            return ResearchAnalysisReport(status="HOLD_SINGULAR", reason="no finite fixed-effect estimates", estimator="BinomialBayesMixedGLM.fit_vb", package_versions=(("statsmodels", statsmodels.__version__),), formula=formula, random_effects=random_effects, converged=True, data_digest=digest)
        return ResearchAnalysisReport(status="ESTIMATED", estimator="BinomialBayesMixedGLM.fit_vb", package_versions=(("statsmodels", statsmodels.__version__),), formula=formula, random_effects=random_effects, converged=True, effects=effects, data_digest=digest)
    except (ValueError, ZeroDivisionError, OverflowError, FloatingPointError) as exc:
        return ResearchAnalysisReport(status="HOLD_SINGULAR", reason=type(exc).__name__, data_digest=digest)
    except Exception as exc:  # noqa: BLE001 - numerical libraries expose heterogeneous convergence failures
        return ResearchAnalysisReport(status="HOLD_NONCONVERGED", reason=type(exc).__name__, data_digest=digest)


def _factor_columns(registered_factors: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(f"factor_{index}" for index, _factor in enumerate(registered_factors))


def _factor_column(factor_id: str, registered_factors: tuple[Any, ...]) -> str:
    for index, factor in enumerate(registered_factors):
        if factor.factor_id == factor_id:
            return f"factor_{index}"
    raise ValueError("interaction contains an unregistered factor")


def _rows(attempts: tuple[Any, ...], registered_factors: tuple[Any, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    names = _factor_columns(registered_factors)
    for attempt in sorted(attempts, key=lambda item: item.attempt_id):
        factors = dict(attempt.factors)
        row: dict[str, Any] = {
            "attempt_id": attempt.attempt_id,
            "task_cluster": attempt.task_cluster_id,
            "stressor": attempt.variant,
            "success": int(attempt.success),
        }
        for name, factor in zip(names, registered_factors, strict=True):
            if factor.factor_id not in factors:
                raise ValueError("eligible record lacks a preregistered factor")
            row[name] = str(factors[factor.factor_id])
        rows.append(row)
    return rows
