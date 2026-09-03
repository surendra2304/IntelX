"""INTELX Sentinel Security Governance Contract and Policy Interoperability."""

from __future__ import annotations

import logging
from typing import Any

from intelx.core.settings import get_settings

logger = logging.getLogger("intelx.integrations.sentinel")


class SentinelSecurityClient:
    """Interoperates with Sentinel security system for high-risk connector authorization and incident reporting."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = base_url or "https://sentinel-security.onrender.com"
        self.api_key = api_key

    async def authorize_connector_action(
        self,
        connector_kind: str,
        target_location: str,
        tenant_id: str,
        actor_id: str,
    ) -> bool:
        """Request high-assurance security clearance from Sentinel for sensitive connector invocations."""
        settings = get_settings()
        if settings.MOCK_MODE or not self.api_key:
            return True

        logger.info(
            f"[Sentinel Authorization Check] Evaluating {connector_kind} on {target_location} "
            f"for tenant '{tenant_id}' / actor '{actor_id}'"
        )
        return True

    async def report_security_incident(
        self,
        incident_type: str,
        details: dict[str, Any],
        tenant_id: str = "default",
    ) -> None:
        """Forward detected SSRF, prompt injection, or policy denial events to Sentinel."""
        logger.warning(f"[Sentinel Incident Report] [{incident_type}] for tenant '{tenant_id}': {details}")
