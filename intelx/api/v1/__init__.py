"""INTELX API v1 Router."""

from fastapi import APIRouter

from intelx.api.v1.endpoints import router as endpoints_router
from intelx.api.v1.friday import router as friday_router
from intelx.api.v1.futuris import router as futuris_router
from intelx.api.v1.health import router as health_router
from intelx.api.v1.subscriptions import router as subscriptions_router
from intelx.api.v1.version import router as version_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(version_router)
v1_router.include_router(health_router)
v1_router.include_router(endpoints_router)
v1_router.include_router(friday_router)
v1_router.include_router(futuris_router)
v1_router.include_router(subscriptions_router)

