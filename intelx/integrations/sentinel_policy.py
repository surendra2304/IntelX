"""INTELX Sentinel Security Governance Contract and Policy Interoperability."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from intelx.core.settings import get_settings

logger = logging.getLogger("intelx.integrations.sentinel")


class SentinelSecurityClient:
    """Interoperates with Sentinel security system for high-risk connector authorization and incident reporting."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "http://sentinel:8000").rstrip("/")
        self.api_key = api_key
        self._transport = transport
        self.incident_log: list[dict[str, Any]] = []

    async def authorize_connector_action(
        self,
        connector_kind: str,
        target_location: str,
        tenant_id: str,
        actor_id: str,
    ) -> bool:
        """Request high-assurance security clearance from Sentinel for sensitive connector invocations."""
        settings = get_settings()
        if settings.MOCK_MODE:
            logger.debug(
                f"[Sentinel Mock Authorization] Granted for {connector_kind} on {target_location}"
            )
            return True
        if not self.api_key:
            logger.error(
                "Sentinel authorization unavailable: API key missing; denying connector action"
            )
            return False

        payload = {
            "connector_kind": connector_kind,
            "target_location": target_location,
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "agent": "intelx",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Agent-Name": "intelx",
        }

        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=5.0, headers=headers
            ) as client:
                resp = await client.post(f"{self.base_url}/v1/policy/authorize", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return bool(data.get("allowed", True))
                logger.warning(
                    f"Sentinel authorization returned HTTP {resp.status_code}; failing closed"
                )
                return False
        except Exception as exc:
            logger.warning(f"Sentinel authorization request failed ({type(exc).__name__}): {exc}")
            return False

    async def report_security_incident(
        self,
        incident_type: str,
        details: dict[str, Any],
        tenant_id: str = "default",
    ) -> dict[str, Any]:
        """Forward detected SSRF, prompt injection, or policy denial events to Sentinel."""
        incident = {
            "incident_type": incident_type,
            "details": details,
            "tenant_id": tenant_id,
            "source_agent": "intelx",
        }
        self.incident_log.append(incident)
        logger.warning(
            f"[Sentinel Incident Report] [{incident_type}] for tenant '{tenant_id}': {details}"
        )

        settings = get_settings()
        if settings.MOCK_MODE:
            return {"status": "reported_mock", "incident": incident}
        if not self.api_key:
            logger.error("Sentinel incident reporting unavailable: API key missing")
            return {"status": "error", "error": "missing_api_key"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Agent-Name": "intelx",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=5.0, headers=headers
            ) as client:
                resp = await client.post(f"{self.base_url}/v1/incidents", json=incident)
                if resp.status_code in (200, 201, 202):
                    return {"status": "reported", "response": resp.json()}
                return {"status": "failed_upstream", "status_code": resp.status_code}
        except Exception as exc:
            logger.warning(f"Sentinel incident reporting failed ({type(exc).__name__}): {exc}")
            return {"status": "error", "error": type(exc).__name__}


__all__ = ["SentinelSecurityClient"]
