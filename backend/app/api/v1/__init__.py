from fastapi import APIRouter

from app.api.v1 import api_keys, organizations, projects

api_router = APIRouter(prefix="/v1")
api_router.include_router(organizations.router)
api_router.include_router(projects.router)
api_router.include_router(api_keys.router)
