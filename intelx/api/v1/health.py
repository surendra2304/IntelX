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
@router.head("/healthz", summary="System Liveness Probe")
@router.get("/health", summary="System Liveness Probe Alias")
@router.head("/health", summary="System Liveness Probe Alias")
async def healthz() -> dict[str, Any]:
    """Liveness probe: verifies process is running and accepting HTTP requests."""
    settings = get_settings()
    db_healthy = await check_database_health()
    observed_at = datetime.now(UTC).isoformat()
    return {
        "status": "ok" if db_healthy else "degraded",
        "evidence_class": "process_liveness",
        "observed_at": observed_at,
        "service": PROJECT_NAME,
        "version": __version__,
        "mock_mode": settings.MOCK_MODE,
        "database": "ok" if db_healthy else "error",
        "timestamp": observed_at,
    }


@router.get("/readyz", summary="Service Readiness Probe")
@router.head("/readyz", summary="Service Readiness Probe")
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

    # 3. Model-provider configuration check. This does not probe upstream reachability;
    # it only verifies that the selected live backend has the required endpoint/key.
    provider_healthy = settings.MOCK_MODE
    if not settings.MOCK_MODE:
        if settings.LLM_PROVIDER in ("inference", "ai_universe", "aiuniverse"):
            provider_healthy = bool(settings.INFERENCE_URL and settings.INFERENCE_API_KEY)
        elif settings.LLM_PROVIDER == "anthropic":
            provider_healthy = bool(settings.get_llm_api_key("anthropic"))
        elif settings.LLM_PROVIDER in {
            "openai_compatible",
            "openai",
            "groq",
            "vllm",
            "ollama",
            "openrouter",
        }:
            provider_healthy = bool(settings.get_llm_api_key("openai_compatible"))

    all_ready = db_healthy and storage_healthy and provider_healthy

    payload = {
        "status": "ready" if all_ready else "not_ready",
        "evidence_class": "dependency_readiness",
        "observed_at": datetime.now(UTC).isoformat(),
        "ready": all_ready,
        "database": "ok" if db_healthy else "error",
        "storage": "ok" if storage_healthy else "error",
        "model_provider": (
            "mock"
            if settings.MOCK_MODE
            else ("configured" if provider_healthy else "misconfigured")
        ),
        "model_provider_check": "local_mock" if settings.MOCK_MODE else "configuration_only",
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
