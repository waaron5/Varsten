from fastapi import APIRouter

from app.api.v1 import (
    api_keys,
    auth,
    metrics,
    organizations,
    projects,
    usage_events,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(projects.router)
api_router.include_router(api_keys.router)
api_router.include_router(usage_events.router)
api_router.include_router(metrics.router)
