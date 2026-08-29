"""INTELX — Futuris Context Exchange and Forecasting API Router."""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.settings import get_settings
from intelx.db.session import get_db_session
from intelx.integrations.futuris_context import (
    CombinedIntelligenceReport,
    ForecastContextRequest,
    ForecastContextResponse,
    FuturisContextProvider,
    ResearchTriggeredForecasting,
    generate_combined_intelligence_report,
)

router = APIRouter(prefix="/futuris", tags=["Futuris Predictive Forecasting Integration"])


class TriggerForecastRequest(BaseModel):
    """Payload to trigger a research-informed forecast update."""

    finding_text: str = Field(..., description="Key factual finding or catalyst")
    run_id: str = Field(..., description="IntelX research run ID")
    domain: str = Field(default="market", description="market | security | technical | general")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    webhook_url: str | None = None


class CombinedReportRequest(BaseModel):
    """Payload to generate a combined research + forecast report."""

    research_data: dict[str, Any] = Field(
        ..., description="IntelX research findings, objective, confidence"
    )
    forecast_data: dict[str, Any] = Field(
        ..., description="Futuris forecast predictions, target, horizon"
    )


async def verify_futuris_auth(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
) -> None:
    """Verify incoming request from Futuris or authorized client."""
    settings = get_settings()
    if settings.MOCK_MODE:
        return

    # Check X-API-Key or Bearer token
    token = x_api_key
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API authentication key for Futuris integration",
        )

    # Valid if matches FUTURIS_API_KEY, FRIDAY_API_KEY, or any configured API_KEYS
    valid_keys = set(settings.API_KEYS)
    if settings.FUTURIS_API_KEY:
        valid_keys.add(settings.FUTURIS_API_KEY)
    if settings.FRIDAY_API_KEY:
        valid_keys.add(settings.FRIDAY_API_KEY)

    if valid_keys and token not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key for Futuris integration endpoint",
        )


@router.post(
    "/context",
    response_model=ForecastContextResponse,
    summary="Fetch Research-Backed Context for Forecast Target",
    dependencies=[Depends(verify_futuris_auth)],
)
async def get_forecast_context(
    request: ForecastContextRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ForecastContextResponse:
    """Provide historical and empirical research context to enrich Futuris forecasting models."""
    ctx_opts = request.requesting_context or {}
    domain = ctx_opts.get("domain", "general")
    lookback = ctx_opts.get("lookback_days", 7)

    response = await FuturisContextProvider.get_research_context(
        session=session,
        forecast_target=request.forecast_target,
        horizon=request.horizon,
        lookback_days=lookback,
        domain=domain,
    )
    return response


@router.post(
    "/trigger-forecast",
    summary="Trigger Automated Forecast Update from Research Finding",
    dependencies=[Depends(verify_futuris_auth)],
)
async def trigger_forecast_update(
    request: TriggerForecastRequest,
) -> dict[str, Any]:
    """Notify Futuris via webhook when IntelX discovers a significant market, regulatory, or security event."""
    result = await ResearchTriggeredForecasting.notify_futuris_research_relevant(
        finding_text=request.finding_text,
        run_id=request.run_id,
        domain=request.domain,
        confidence=request.confidence,
        webhook_url=request.webhook_url,
    )
    return result


@router.post(
    "/combined-report",
    response_model=CombinedIntelligenceReport,
    summary="Generate Unified Research + Forecast Intelligence Report",
    dependencies=[Depends(verify_futuris_auth)],
)
async def create_combined_report(
    request: CombinedReportRequest,
) -> CombinedIntelligenceReport:
    """Synthesize IntelX evidence-backed 'Why' with Futuris calibrated 'What Next' into a single product."""
    report = generate_combined_intelligence_report(
        research_data=request.research_data,
        forecast_data=request.forecast_data,
    )
    return report
