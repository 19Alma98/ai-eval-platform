from fastapi import APIRouter

from aiobs.api.routes.app_configs import router as app_configs_router
from aiobs.api.routes.datasets import router as datasets_router
from aiobs.api.routes.evaluators import router as evaluators_router
from aiobs.api.routes.experiments import router as experiments_router
from aiobs.api.routes.metrics_packs import router as metrics_packs_router
from aiobs.api.routes.otlp import router as otlp_router
from aiobs.api.routes.projects import router as projects_router
from aiobs.api.routes.release import router as release_router
from aiobs.api.routes.traces import router as traces_router

api_router = APIRouter()
api_router.include_router(projects_router)
api_router.include_router(app_configs_router)
api_router.include_router(traces_router)
api_router.include_router(datasets_router)
api_router.include_router(evaluators_router)
api_router.include_router(metrics_packs_router)
api_router.include_router(experiments_router)
api_router.include_router(release_router)
api_router.include_router(otlp_router)
