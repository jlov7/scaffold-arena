from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.deps import limiter, validate_scaffold_ids, validate_task_id
from core.auth import verify_token

router = APIRouter(tags=["autopsy"])


class AutopsyRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    scaffold_id: str = Field(min_length=1, max_length=128)
    output: str = Field(min_length=1, max_length=200_000)
    evaluation: dict
    metrics: dict | None = None


@router.post("/api/autopsy")
@limiter.limit("10/minute")
async def autopsy(
    request: Request,
    req: AutopsyRequest,
    _auth: None = Depends(verify_token),
):
    from autopsy.analyzer import analyze_failures

    validate_task_id(req.task_id)
    validate_scaffold_ids([req.scaffold_id])
    return await analyze_failures(
        task_id=req.task_id,
        scaffold_id=req.scaffold_id,
        output=req.output,
        evaluation=req.evaluation,
        metrics=req.metrics,
    )
