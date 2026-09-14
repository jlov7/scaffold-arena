from fastapi import APIRouter

from api.deps import settings
from build_meta import build_metadata
from config.models import all_models_meta
from core.registry import all_scaffolds_meta, all_tasks_meta

router = APIRouter(tags=["metadata"])


@router.get("/api/health")
async def health():
    return {"status": "ok"}


@router.get("/api/meta")
async def meta():
    return {
        "build": build_metadata(),
        "models": all_models_meta(),
        "tasks": all_tasks_meta(),
        "scaffolds": all_scaffolds_meta(),
        "features": {
            "llm_judge": settings.enable_llm_judge,
            "pdf_export": settings.enable_pdf_export,
            "evaluation_profiles": ["balanced", "strict", "cost_first"],
        },
        "limits": {
            "max_cost_per_run_usd": settings.max_cost_per_run_usd,
        },
    }


@router.get("/api/build-meta")
async def build_meta():
    return build_metadata()
