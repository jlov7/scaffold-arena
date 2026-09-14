from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.deps import limiter, settings, validate_model_id, validate_task_id
from core.auth import verify_token

router = APIRouter(tags=["reports"])


class ReportRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    results: dict
    comparison: dict | None = None
    autopsy: dict | None = None
    patch_rerun: dict | None = None


@router.post("/api/reports")
@limiter.limit("10/minute")
async def generate_report(
    request: Request,
    req: ReportRequest,
    _auth: None = Depends(verify_token),
):
    from report.markdown import generate_markdown

    validate_task_id(req.task_id)
    validate_model_id(req.model_id)
    markdown = generate_markdown(
        task_id=req.task_id,
        model_id=req.model_id,
        results=req.results,
        comparison=req.comparison,
        autopsy=req.autopsy,
        patch_rerun=req.patch_rerun,
    )
    response: dict = {"markdown": markdown}
    if settings.enable_pdf_export:
        try:
            from report.pdf import generate_pdf

            response["pdf_base64"] = generate_pdf(markdown)
        except ImportError:
            response["pdf_base64"] = None
    else:
        response["pdf_base64"] = None
    return response
