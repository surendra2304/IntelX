"""Health and readiness check endpoints."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from intelx.core.settings import get_settings
from intelx.core.version import PROJECT_NAME, __version__
from intelx.db.session import check_database_health

router = APIRouter(tags=["Health"])


@router.get("/healthz", summary="System Health Check")
async def healthz() -> dict[str, Any]:
    """Return platform operational status, database connectivity, and mock mode status."""
    settings = get_settings()
    db_healthy = await check_database_health()

    payload = {
        "status": "ok" if db_healthy else "degraded",
        "service": PROJECT_NAME,
        "version": __version__,
        "mock_mode": settings.MOCK_MODE,
        "database": "ok" if db_healthy else "error",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if not db_healthy:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)

    return payload


@router.get("/readyz", summary="Service Readiness Probe")
async def readyz() -> dict[str, Any]:
    """Readiness probe for load balancers and container orchestrators."""
    db_healthy = await check_database_health()
    if not db_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "ready": False, "database": "error"},
        )
    return {"status": "ready", "ready": True, "database": "ok"}
