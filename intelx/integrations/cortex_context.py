"""INTELX — Cortex Website Operations & Lead Intelligence Integration.

Cortex (Agent 6) is the Website Agent of the FRIDAY Universe.
It manages website visitors, captures and qualifies leads, answers visitor inquiries
with real-time product and industry knowledge, and optimizes website conversions.

IntelX acts as the autonomous research and OSINT engine powering Cortex:
  1. Lead Dossier Enrichment: Researches companies, domains, and prospects to enrich leads.
  2. Visitor Query Fact-Checking: Provides cited, verified research to answer visitor queries.
  3. Outbound Webhook Delivery: Dispatches web trends, competitor intelligence, and prospect signals.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from intelx.core.settings import get_settings

logger = logging.getLogger("intelx.integrations.cortex")


class CortexLeadDossier(BaseModel):
    """Enriched intelligence dossier for a website lead or prospective client domain."""

    target_domain: str
    company_name: str | None = None
    industry: str | None = None
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    talking_points_for_cortex: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    confidence: float = 0.85
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class CortexLeadIntelResponse(BaseModel):
    """Response returned by Cortex after processing web intelligence or lead enrichment."""

    status: str
    action_taken: str
    lead_id: str | None = None
    enrichment_status: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class CortexConnector:
    """Handles bidirectional communication with Cortex for website visitor & lead intelligence."""

    # Keywords signaling high-value website visitor or B2B lead intelligence
    LEAD_KEYWORDS = {
        "lead",
        "visitor",
        "prospect",
        "conversion",
        "client",
        "customer",
        "enterprise",
        "b2b",
        "saas",
        "pricing",
        "signup",
        "demo",
        "pipeline",
        "competitor",
        "market share",
        "feature",
        "integration",
        "acquisition",
        "partnership",
        "launch",
        "website",
        "landing page",
        "seo",
    }

    @classmethod
    def detect_lead_relevance(
        cls, finding_text: str, domain: str = "general"
    ) -> tuple[bool, str, list[str]]:
        """Identify if a finding contains actionable lead or website visitor intelligence."""
        txt_lower = finding_text.lower()
        if any(k in txt_lower for k in cls.LEAD_KEYWORDS):
            return True, "actionable_lead_intel", ["WEBSITE_PROSPECT"]
        return True, "general_web_intel", []  # Always forward; let Cortex decide conversion utility

    @classmethod
    async def notify_cortex_lead_intel(
        cls,
        finding_text: str,
        run_id: str,
        domain: str = "general",
        confidence: float = 0.85,
        webhook_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Notify Cortex via webhook that actionable website or lead intelligence was discovered.

        extra_context carries the full structured IntelX research payload:
        findings list, top claims, executive answer, source count, claims count.
        Cortex uses this to enrich visitor interactions and qualify leads.
        """
        settings = get_settings()
        target_url = (
            webhook_url
            or settings.CORTEX_WEBHOOK_URL
            or f"{settings.CORTEX_BASE_URL}/api/v1/webhooks/intelx-lead-intel"
        )

        is_sig, category, targets = cls.detect_lead_relevance(finding_text, domain=domain)

        data_block: dict[str, Any] = {
            "run_id": run_id,
            "finding_summary": finding_text,
            "category": category,
            "confidence": confidence,
            "domain": domain,
            "recommended_targets": targets,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if extra_context:
            data_block["research_intel"] = extra_context

        payload = {
            "event": "website_lead_intel",
            "data": data_block,
        }

        from intelx.integrations.memora_events import publish_research_notice

        memora_event = await publish_research_notice(
            target_agent="cortex",
            run_id=run_id,
            finding_summary=finding_text,
            category=category,
            domain=domain,
            confidence=confidence,
            recommended_targets=targets,
            sources=(extra_context or {}).get("sources", []),
        )

        if settings.MOCK_MODE or not target_url:
            logger.info(
                f"[Cortex Webhook Simulated] Dispatched website_lead_intel for run {run_id}: {category}"
            )
            return {
                "status": "delivered_mock",
                "event": "website_lead_intel",
                "category": category,
                "payload": payload,
                "memora_event": memora_event,
            }

        try:
            headers = {"Content-Type": "application/json"}
            if settings.CORTEX_API_KEY:
                headers["X-API-Key"] = settings.CORTEX_API_KEY

            if client:
                resp = await client.post(target_url, json=payload, headers=headers, timeout=8.0)
                status_code = resp.status_code
            else:
                async with httpx.AsyncClient(timeout=8.0) as http_c:
                    resp = await http_c.post(target_url, json=payload, headers=headers)
                    status_code = resp.status_code

            logger.info(
                f"[Cortex] Webhook delivered HTTP {status_code} for run {run_id} "
                f"({len(extra_context.get('findings', [])) if extra_context else 0} findings)"
            )
            return {
                "status": "delivered" if status_code < 300 else "failed_upstream",
                "status_code": status_code,
                "event": "website_lead_intel",
                "category": category,
                "payload": payload,
                "memora_event": memora_event,
            }
        except Exception as ex:
            logger.warning(f"Failed to deliver Cortex webhook to {target_url}: {ex}")
            return {
                "status": "error",
                "error": str(ex),
                "event": "website_lead_intel",
                "category": category,
                "payload": payload,
                "memora_event": memora_event,
            }

    @classmethod
    def extract_domain(cls, domain_or_email: str) -> str:
        """Extract clean domain name from URL, email, or domain string."""
        s = domain_or_email.strip().lower()
        if "@" in s:
            s = s.split("@")[-1]
        s = re.sub(r"^https?://", "", s)
        s = s.split("/")[0].split(":")[0]
        return s

    @classmethod
    def synthesize_lead_dossier(
        cls,
        target_domain: str,
        findings: list[dict[str, Any]] | None = None,
        claims: list[dict[str, Any]] | None = None,
    ) -> CortexLeadDossier:
        """Synthesize a structured prospect dossier from research findings and claims."""
        clean_domain = cls.extract_domain(target_domain)
        name_guess = clean_domain.split(".")[0].title()

        key_findings: list[str] = []
        talking_points: list[str] = []
        competitors: list[str] = []

        if findings:
            for f in findings:
                conclusion = f.get("conclusion") or f.get("statement") or ""
                if conclusion:
                    key_findings.append(conclusion)
                    talking_points.append(f"Mention how FRIDAY addresses: {conclusion[:120]}")

        if not key_findings and claims:
            for c in claims[:5]:
                txt = c.get("text") or c.get("quote") or ""
                if txt:
                    key_findings.append(txt)

        if not key_findings:
            key_findings.append(f"Autonomous web intelligence collected for {clean_domain}.")
            talking_points.append(
                f"Introduce FRIDAY automation solutions tailored for {clean_domain}."
            )

        return CortexLeadDossier(
            target_domain=clean_domain,
            company_name=name_guess,
            industry="Technology / Enterprise",
            summary=f"OSINT intelligence dossier for prospective website visitor/lead from {clean_domain}.",
            key_findings=key_findings,
            talking_points_for_cortex=talking_points,
            competitors=competitors,
            confidence=0.85,
        )


__all__ = [
    "CortexConnector",
    "CortexLeadDossier",
    "CortexLeadIntelResponse",
]
