from fastapi import APIRouter

from app.api.v1 import (
    api_keys,
    auth,
    evals,
    metrics,
    organizations,
    product_sections,
    projects,
    recommendations,
    usage_events,
)
from app.proxy.router import router as proxy_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(projects.router)
api_router.include_router(api_keys.router)
api_router.include_router(usage_events.router)
api_router.include_router(metrics.router)
api_router.include_router(recommendations.router)
api_router.include_router(evals.router)
api_router.include_router(product_sections.router)
# Phase 1 inline proxy: POST /v1/chat/completions (OpenAI mirror).
api_router.include_router(proxy_router)
