"""
IntelX/routers/intel_sharing_manager.py — IntelX Intel Sharing Manager.

STIX/TAXII sharing, threat intel exchange, sharing agreements,
and intelligence dissemination.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class IntelExchange:
    """A threat intelligence exchange."""
    exchange_id: str
    sender: str
    recipient: str
    intel_type: str = "IoC"  # IoC, TTP, vulnerability, threat_actor
    content: str = ""
    stix_package: str = ""
    status: str = "pending"  # pending, sent, received, acknowledged
    sent_at: float = 0.0
    acknowledged_at: float = 0.0


@dataclass
class SharingAgreement:
    """A sharing agreement between organizations."""
    agreement_id: str
    organization: str
    allowed_intel_types: list[str] = field(default_factory=list)
    reciprocal: bool = False
    ttl_hours: float = 0.0
    status: str = "active"
    created_at: float = field(default_factory=time.time)


@dataclass
class SharingPolicy:
    """A sharing policy for intelligence."""
    policy_id: str
    name: str
    rules: list[dict] = field(default_factory=list)
    auto_share: bool = False
    classification: str = "TLP:AMBER"


class IntelSharingManager:
    """Manager for threat intelligence sharing."""

    def __init__(self) -> None:
        self._exchanges: dict[str, IntelExchange] = {}
        self._agreements: dict[str, SharingAgreement] = {}
        self._policies: dict[str, SharingPolicy] = {}

    def create_agreement(self, organization: str, intel_types: list[str],
                         reciprocal: bool = False, ttl_hours: float = 0.0) -> str:
        """Create a sharing agreement."""
        agreement_id = f"sa_{uuid.uuid4().hex[:12]}"
        agreement = SharingAgreement(
            agreement_id=agreement_id, organization=organization,
            allowed_intel_types=intel_types, reciprocal=reciprocal, ttl_hours=ttl_hours,
        )
        self._agreements[agreement_id] = agreement
        return agreement_id

    def create_policy(self, name: str, rules: list[dict], auto_share: bool = False,
                      classification: str = "TLP:AMBER") -> str:
        """Create a sharing policy."""
        policy_id = f"sp_{uuid.uuid4().hex[:12]}"
        policy = SharingPolicy(
            policy_id=policy_id, name=name, rules=rules,
            auto_share=auto_share, classification=classification,
        )
        self._policies[policy_id] = policy
        return policy_id

    def share_intel(self, sender: str, recipient: str, intel_type: str,
                    content: str) -> str:
        """Share intelligence with another organization."""
        exchange_id = f"ex_{uuid.uuid4().hex[:12]}"
        exchange = IntelExchange(
            exchange_id=exchange_id, sender=sender, recipient=recipient,
            intel_type=intel_type, content=content,
        )
        exchange.status = "sent"
        exchange.sent_at = time.time()
        self._exchanges[exchange_id] = exchange
        return exchange_id

    def acknowledge_exchange(self, exchange_id: str) -> bool:
        """Acknowledge receipt of shared intelligence."""
        exchange = self._exchanges.get(exchange_id)
        if not exchange:
            return False
        exchange.status = "acknowledged"
        exchange.acknowledged_at = time.time()
        return True

    def get_exchanges(self, status: str | None = None) -> list[dict[str, Any]]:
        """Get intelligence exchanges."""
        exchanges = list(self._exchanges.values())
        if status:
            exchanges = [e for e in exchanges if e.status == status]
        return [
            {
                "exchange_id": e.exchange_id,
                "sender": e.sender,
                "recipient": e.recipient,
                "intel_type": e.intel_type,
                "status": e.status,
            }
            for e in exchanges
        ]

    def get_agreements(self) -> list[dict[str, Any]]:
        """Get sharing agreements."""
        return [
            {
                "agreement_id": a.agreement_id,
                "organization": a.organization,
                "intel_types": a.allowed_intel_types,
                "status": a.status,
            }
            for a in self._agreements.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_exchanges": len(self._exchanges),
            "total_agreements": len(self._agreements),
            "total_policies": len(self._policies),
            "acknowledged": sum(1 for e in self._exchanges.values() if e.status == "acknowledged"),
            "engine_status": "operational",
        }


engine = IntelSharingManager()


@router.post("/intelex/sharing/agreements")
async def create_agreement(organization: str, intel_types: list[str],
                           reciprocal: bool = False, ttl_hours: float = 0.0):
    """Create a sharing agreement."""
    agreement_id = engine.create_agreement(organization, intel_types, reciprocal, ttl_hours)
    return {"agreement_id": agreement_id, "status": "created"}


@router.post("/intelex/sharing/exchanges")
async def share_intel(sender: str, recipient: str, intel_type: str, content: str):
    """Share intelligence."""
    exchange_id = engine.share_intel(sender, recipient, intel_type, content)
    return {"exchange_id": exchange_id, "status": "sent"}


@router.post("/intelex/sharing/exchanges/{exchange_id}/acknowledge")
async def acknowledge_exchange(exchange_id: str):
    """Acknowledge receipt of shared intelligence."""
    if not engine.acknowledge_exchange(exchange_id):
        raise HTTPException(status_code=404, detail="Exchange not found")
    return {"exchange_id": exchange_id, "status": "acknowledged"}


@router.get("/intelex/sharing/exchanges")
async def get_exchanges(status: str | None = None):
    """Get intelligence exchanges."""
    return {"exchanges": engine.get_exchanges(status)}


@router.get("/intelex/sharing/agreements")
async def get_agreements():
    """Get sharing agreements."""
    return {"agreements": engine.get_agreements()}


@router.get("/intelex/sharing/report")
async def sharing_report():
    """Get sharing manager report."""
    return engine.get_report()
