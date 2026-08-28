"""INTELX API v1 Router."""

from fastapi import APIRouter

from intelx.api.v1.health import router as health_router
from intelx.api.v1.version import router as version_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(version_router)
v1_router.include_router(health_router)
