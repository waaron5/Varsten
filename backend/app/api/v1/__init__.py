from fastapi import APIRouter

from app.api.v1 import (
    api_keys,
    auth,
    batches,
    billing,
    entitlements,
    evals,
    feedback,
    metrics,
    onboarding,
    operator,
    organizations,
    product_sections,
    projects,
    recommendations,
    telemetry,
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
api_router.include_router(operator.router)
api_router.include_router(recommendations.router)
api_router.include_router(evals.router)
api_router.include_router(feedback.router)
api_router.include_router(onboarding.router)
api_router.include_router(entitlements.router)
api_router.include_router(billing.router)
api_router.include_router(product_sections.router)
# Fail-open SDK fallback telemetry: POST /v1/telemetry/fallback.
api_router.include_router(telemetry.router)
# Phase 1 inline proxy: POST /v1/chat/completions (OpenAI mirror).
api_router.include_router(proxy_router)
# Batching lever: the async /v1/batches mirror.
api_router.include_router(batches.router)
