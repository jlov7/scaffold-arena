from fastapi import APIRouter

from .analysis import router as analysis_router
from .auth import router as auth_router
from .decision import router as decision_router
from .evidence import router as evidence_router
from .execution import router as execution_router
from .exports import router as exports_router
from .genome import router as genome_router
from .planning import router as planning_router
from .registry import router as registry_router
from .retention import router as retention_router
from .review import router as review_router
from .settings import router as settings_router
from .trace_lab import router as trace_lab_router
from .xray import router as xray_router
from .observatory import router as observatory_router
from .counterfactual import router as counterfactual_router
from .forge import router as forge_router
from .offline_demo import router as offline_demo_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(settings_router)
router.include_router(retention_router)
router.include_router(analysis_router)
router.include_router(planning_router)
router.include_router(decision_router)
router.include_router(registry_router)
router.include_router(execution_router)
router.include_router(evidence_router)
router.include_router(exports_router)
router.include_router(genome_router)
router.include_router(review_router)
router.include_router(trace_lab_router)
router.include_router(xray_router)
router.include_router(observatory_router)
router.include_router(counterfactual_router)
router.include_router(forge_router)
router.include_router(offline_demo_router)

__all__ = [
    "analysis_router",
    "auth_router",
    "decision_router",
    "evidence_router",
    "execution_router",
    "exports_router",
    "genome_router",
    "planning_router",
    "registry_router",
    "retention_router",
    "review_router",
    "router",
    "settings_router",
    "trace_lab_router",
    "xray_router",
    "observatory_router",
    "counterfactual_router",
    "forge_router",
]
