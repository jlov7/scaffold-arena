"""Provider-free prospective analysis-plan assessment."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from analysis_v1 import assess_analysis_plan
from protocol_v1 import ExperimentSpec
from protocol_v1.canonical import canonical_json

router = APIRouter(prefix="/api/v1/analysis-plans", tags=["analysis-plans"])

_INVALID = {
    "error": {
        "code": "invalid_analysis_plan_request",
        "message": "A strict protocol-v1 ExperimentSpec JSON object is required.",
    }
}


@router.post("/assess", response_model=None)
def assess_frozen_analysis_plan(
    payload: dict[str, Any] = Body(...),
) -> JSONResponse | dict[str, Any]:
    """Assess frozen prospective intent without providers, results, or project data."""

    try:
        spec = ExperimentSpec.model_validate_json(canonical_json(payload))
    except (TypeError, ValueError, ValidationError):
        return JSONResponse(status_code=400, content=_INVALID)

    assessment = assess_analysis_plan(spec)
    value = assessment.model_dump(mode="json")
    if assessment.status == "HOLD":
        return JSONResponse(
            status_code=409,
            content={"verdict": "HOLD", "assessment": value},
        )
    if assessment.status == "INVALID":
        return JSONResponse(
            status_code=400,
            content={"verdict": "HOLD", "assessment": value},
        )
    return value
