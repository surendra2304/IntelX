"""INTELX Continuous Research Subscriptions and Delta Updates API Router."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from intelx.core.auth import Principal, get_current_principal
from intelx.core.delta_research import DeltaResearch

router = APIRouter(prefix="/subscriptions", tags=["Continuous Research Subscriptions"])

# In-memory subscription store for active fleet tracking
_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {}
_delta_engine = DeltaResearch()


class CreateSubscriptionRequest(BaseModel):
    """Payload to create a continuous research subscription."""

    objective: str = Field(..., description="Target research objective")
    schedule_cron: str = Field(default="0 0 * * *", description="Cron schedule expression")
    search_scope: dict[str, Any] = Field(default_factory=dict)
    budget_usd: float = Field(default=5.0, ge=0.5, le=50.0)
    notification_webhook: str | None = None


class SubscriptionResponse(BaseModel):
    """Structured response for an active research subscription."""

    id: str
    tenant_id: str
    principal_id: str
    objective: str
    schedule_cron: str
    status: str
    last_run_id: str | None = None
    created_at: str


@router.post(
    "",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Continuous Research Subscription",
)
async def create_subscription(
    req: CreateSubscriptionRequest,
    principal: Principal = Depends(get_current_principal),
) -> SubscriptionResponse:
    """Register a new recurring research subscription with delta tracking."""
    sub_id = f"sub_{uuid4().hex[:12]}"
    record = {
        "id": sub_id,
        "tenant_id": principal.tenant_id,
        "principal_id": principal.actor_id,
        "objective": req.objective,
        "schedule_cron": req.schedule_cron,
        "search_scope": req.search_scope,
        "budget_usd": req.budget_usd,
        "status": "ACTIVE",
        "last_run_id": None,
        "created_at": "2026-09-03T00:00:00Z",
    }
    _SUBSCRIPTIONS[sub_id] = record
    return SubscriptionResponse(**record)


@router.get(
    "/{subscription_id}",
    response_model=SubscriptionResponse,
    summary="Get Subscription Status",
)
async def get_subscription(
    subscription_id: str,
    principal: Principal = Depends(get_current_principal),
) -> SubscriptionResponse:
    """Retrieve details for a specific research subscription."""
    sub = _SUBSCRIPTIONS.get(subscription_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    if sub["tenant_id"] != principal.tenant_id and "*" not in principal.scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-tenant subscription access denied")
    return SubscriptionResponse(**sub)


@router.post(
    "/{subscription_id}/pause",
    response_model=SubscriptionResponse,
    summary="Pause Continuous Research Subscription",
)
async def pause_subscription(
    subscription_id: str,
    principal: Principal = Depends(get_current_principal),
) -> SubscriptionResponse:
    """Pause an active research subscription."""
    sub = _SUBSCRIPTIONS.get(subscription_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    if sub["tenant_id"] != principal.tenant_id and "*" not in principal.scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-tenant subscription access denied")
    sub["status"] = "PAUSED"
    return SubscriptionResponse(**sub)


@router.post(
    "/{subscription_id}/resume",
    response_model=SubscriptionResponse,
    summary="Resume Continuous Research Subscription",
)
async def resume_subscription(
    subscription_id: str,
    principal: Principal = Depends(get_current_principal),
) -> SubscriptionResponse:
    """Resume a paused research subscription."""
    sub = _SUBSCRIPTIONS.get(subscription_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    if sub["tenant_id"] != principal.tenant_id and "*" not in principal.scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-tenant subscription access denied")
    sub["status"] = "ACTIVE"
    return SubscriptionResponse(**sub)
