"""INTELX — StrateX Algorithmic Trading Integration.

Enables automated market trading decisions based on IntelX research outcomes.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from intelx.core.settings import get_settings

logger = logging.getLogger("intelx.integrations.stratex")


class StratexSignalResponse(BaseModel):
    """Response returned by StrateX after processing a trade signal."""
    
    status: str
    action_taken: str
    asset: str | None = None
    confidence: float | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class StratexConnector:
    """Handles communication with StrateX for automated trade execution."""
    
    TRADE_KEYWORDS = {"bullish", "bearish", "surge", "plummet", "buy", "sell", "breakout", "rally", "catalyst"}

    @classmethod
    def detect_trade_signal(cls, finding_text: str, domain: str = "market") -> tuple[bool, str, list[str]]:
        """Identify if a finding contains actionable trade signals."""
        if domain not in ("market", "finance", "crypto", "equity"):
            return False, "non_market_domain", []

        txt_lower = finding_text.lower()
        if any(k in txt_lower for k in cls.TRADE_KEYWORDS):
            return True, "actionable_trade_signal", ["MARKET_ASSET"]
            
        return False, "no_signal", []

    @classmethod
    async def notify_stratex_trade_signal(
        cls,
        finding_text: str,
        run_id: str,
        domain: str = "market",
        confidence: float = 0.85,
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Notify StrateX via webhook that actionable research was identified."""
        settings = get_settings()
        target_url = (
            webhook_url
            or settings.STRATEX_WEBHOOK_URL
            or f"{settings.STRATEX_BASE_URL}/api/v1/webhooks/intelx-signal"
        )

        is_sig, category, targets = cls.detect_trade_signal(finding_text, domain=domain)
        
        payload = {
            "event": "research_trade_signal",
            "data": {
                "run_id": run_id,
                "finding_summary": finding_text,
                "category": category,
                "confidence": confidence,
                "domain": domain,
                "suggested_assets": targets,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        }

        if settings.MOCK_MODE or not settings.STRATEX_WEBHOOK_URL:
            logger.info(
                f"[StrateX Webhook Simulated] Dispatched research_trade_signal for run {run_id}: {category}"
            )
            return {
                "status": "delivered_mock",
                "event": "research_trade_signal",
                "category": category,
                "payload": payload,
            }

        try:
            headers = {"Content-Type": "application/json"}
            if settings.STRATEX_API_KEY:
                headers["X-API-Key"] = settings.STRATEX_API_KEY

            if client:
                resp = await client.post(target_url, json=payload, headers=headers, timeout=5.0)
                status_code = resp.status_code
            else:
                async with httpx.AsyncClient(timeout=5.0) as http_c:
                    resp = await http_c.post(target_url, json=payload, headers=headers)
                    status_code = resp.status_code

            logger.info(f"StrateX webhook response {status_code} from {target_url}")
            return {
                "status": "delivered" if status_code < 300 else "failed_upstream",
                "status_code": status_code,
                "event": "research_trade_signal",
                "category": category,
                "payload": payload,
            }
        except Exception as ex:
            logger.warning(f"Failed to deliver StrateX webhook to {target_url}: {ex}")
            return {
                "status": "error",
                "error": str(ex),
                "event": "research_trade_signal",
                "category": category,
                "payload": payload,
            }
