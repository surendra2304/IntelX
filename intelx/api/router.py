"""Main API router combining all endpoint groups."""

from fastapi import APIRouter

from intelx.api.v1 import v1_router
from intelx.api.v1.health import router as health_root_router

root_api_router = APIRouter()

# Root health endpoints (/healthz, /readyz)
root_api_router.include_router(health_root_router)

# Versioned API routes (/api/v1/...)
root_api_router.include_router(v1_router)
