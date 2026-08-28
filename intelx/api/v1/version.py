"""Version information endpoint."""

from typing import Any

from fastapi import APIRouter

from intelx.core.settings import get_settings
from intelx.core.version import PROJECT_NAME, __version__

router = APIRouter(tags=["Version"])


@router.get("/version", summary="Platform Version Metadata")
async def get_version_info() -> dict[str, Any]:
    """Return platform version, runtime environment, and active provider modes."""
    settings = get_settings()
    return {
        "name": PROJECT_NAME,
        "version": __version__,
        "env": settings.ENV,
        "mock_mode": settings.MOCK_MODE,
        "llm_provider": settings.LLM_PROVIDER,
    }
