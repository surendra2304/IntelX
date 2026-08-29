import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from intelx.core.metrics import get_metrics_payload
from intelx.core.settings import get_settings
from intelx.core.version import PROJECT_NAME, __version__
from intelx.db.session import check_database_health

router = APIRouter(tags=["Health & Telemetry"])


@router.get("/healthz", summary="System Liveness Probe")
async def healthz() -> dict[str, Any]:
    """Liveness probe: verifies process is running and accepting HTTP requests."""
    settings = get_settings()
    db_healthy = await check_database_health()
    return {
        "status": "ok" if db_healthy else "degraded",
        "service": PROJECT_NAME,
        "version": __version__,
        "mock_mode": settings.MOCK_MODE,
        "database": "ok" if db_healthy else "error",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/readyz", summary="Service Readiness Probe")
async def readyz() -> dict[str, Any]:
    """Readiness probe: verifies database connectivity, storage writeability, and provider readiness."""
    settings = get_settings()

    # 1. Database Connectivity Check
    db_healthy = await check_database_health()

    # 2. Local Storage Writable Check
    storage_healthy = False
    try:
        data_dir = Path(settings.DATA_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=data_dir, delete=True) as tf:
            tf.write(b"readyz_probe\n")
            tf.flush()
        storage_healthy = True
    except Exception:
        storage_healthy = False

    # 3. Model Provider Availability Check
    # (Mock mode is always ready; live mode is ready if provider configured or fallback enabled)
    provider_healthy = True
    if not settings.MOCK_MODE:
        if settings.LLM_PROVIDER in ("ai_universe", "aiuniverse"):
            provider_healthy = bool(settings.AI_UNIVERSE_BASE_URL)
        elif settings.LLM_PROVIDER in ("openai_compatible", "anthropic"):
            provider_healthy = bool(settings.LLM_API_KEY)

    all_ready = db_healthy and storage_healthy and provider_healthy

    payload = {
        "status": "ready" if all_ready else "not_ready",
        "ready": all_ready,
        "database": "ok" if db_healthy else "error",
        "storage": "ok" if storage_healthy else "error",
        "model_provider": "ok" if provider_healthy else "degraded",
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if not all_ready:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)

    return payload


@router.get("/metrics", summary="Prometheus Telemetry Metrics")
async def metrics() -> Response:
    """Expose Prometheus-formatted operational telemetry metrics."""
    content, content_type = get_metrics_payload()
    return Response(content=content, media_type=content_type)
