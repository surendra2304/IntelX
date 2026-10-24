"""
IntelX/intelx/services/threat_intel_exchange_protocol.py — IntelX Threat Intel Exchange Protocol.

STIX/TAXII compatibility, intelligence sharing protocols,
confidence-weighted intel exchange, and partner intel management.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class IntelPackage:
    """An intelligence package for exchange."""
    package_id: str
    stix_version: str = "2.1"
    content: dict = field(default_factory=dict)
    source: str = ""
    confidence: float = 0.5
    sharing_level: str = "restricted"  # restricted, community, TLP:White, TLP:Green, TLP:Amber, TLP:Red
    created_at: float = field(default_factory=time.time)


@dataclass
class ExchangePartner:
    """An intelligence exchange partner."""
    partner_id: str
    name: str
    stix_version: str = "2.1"
    taxii_endpoint: str = ""
    authentication: str = "api_key"  # api_key, cert, oauth2
    trust_level: float = 0.5
    active: bool = True


@dataclass
class ExchangeRecord:
    """A record of an intelligence exchange."""
    exchange_id: str
    source_partner: str
    target_partner: str
    package_count: int = 0
    status: str = "completed"  # pending, completed, failed
    errors: list[str] = field(default_factory=list)
    exchanged_at: float = field(default_factory=time.time)


class ThreatIntelExchangeProtocol:
    """Engine for threat intelligence exchange."""

    def __init__(self) -> None:
        self._packages: dict[str, IntelPackage] = {}
        self._partners: dict[str, ExchangePartner] = {}
        self._exchanges: list[ExchangeRecord] = []

    def create_package(self, content: dict, source: str = "",
                       confidence: float = 0.5,
                       sharing_level: str = "restricted") -> IntelPackage:
        """Create an intelligence package."""
        package_id = f"pkg_{uuid.uuid4().hex[:12]}"
        package = IntelPackage(
            package_id=package_id, content=content,
            source=source, confidence=confidence,
            sharing_level=sharing_level,
        )
        self._packages[package_id] = package
        return package

    def register_partner(self, name: str, stix_version: str = "2.1",
                         taxii_endpoint: str = "", authentication: str = "api_key",
                         trust_level: float = 0.5) -> ExchangePartner:
        """Register an exchange partner."""
        partner_id = f"par_{uuid.uuid4().hex[:12]}"
        partner = ExchangePartner(
            partner_id=partner_id, name=name, stix_version=stix_version,
            taxii_endpoint=taxii_endpoint, authentication=authentication,
            trust_level=trust_level,
        )
        self._partners[partner_id] = partner
        return partner

    def exchange(self, source_partner_id: str, target_partner_id: str,
                 package_ids: list[str]) -> ExchangeRecord:
        """Exchange intelligence packages."""
        source = self._partners.get(source_partner_id)
        target = self._partners.get(target_partner_id)
        if not source or not target:
            raise HTTPException(status_code=404, detail="Partner not found")

        exchange_id = f"ex_{uuid.uuid4().hex[:12]}"
        exchange = ExchangeRecord(
            exchange_id=exchange_id, source_partner=source.name,
            target_partner=target.name, package_count=len(package_ids),
        )

        # Validate packages
        for pid in package_ids:
            pkg = self._packages.get(pid)
            if not pkg:
                exchange.status = "failed"
                exchange.errors.append(f"Package {pid} not found")
                continue

            # Check sharing level compatibility
            if pkg.sharing_level == "TLP:Red" and target.trust_level < 0.8:
                exchange.errors.append(f"Package {pid} too sensitive for partner")

        self._exchanges.append(exchange)
        return exchange

    def export_stix(self, package_id: str) -> dict[str, Any]:
        """Export a package in STIX format."""
        pkg = self._packages.get(package_id)
        if not pkg:
            raise HTTPException(status_code=404, detail="Package not found")
        return {
            "type": "bundle",
            "spec_version": pkg.stix_version,
            "id": f"bundle--{pkg.package_id}",
            "objects": pkg.content,
            "confidence": pkg.confidence,
            "sharing_level": pkg.sharing_level,
        }

    def get_packages(self, sharing_level: str | None = None) -> list[dict[str, Any]]:
        """Get packages."""
        packages = list(self._packages.values())
        if sharing_level:
            packages = [p for p in packages if p.sharing_level == sharing_level]
        return [
            {"source": p.source, "confidence": p.confidence,
             "sharing_level": p.sharing_level, "content_size": len(p.content)}
            for p in packages
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_packages": len(self._packages),
            "total_partners": len(self._partners),
            "total_exchanges": len(self._exchanges),
            "completed_exchanges": sum(1 for e in self._exchanges if e.status == "completed"),
            "engine_status": "operational",
        }


engine = ThreatIntelExchangeProtocol()


@router.post("/intelx/exchange/packages")
async def create_package(content: dict, source: str = "", confidence: float = 0.5,
                         sharing_level: str = "restricted"):
    """Create an intelligence package."""
    pkg = engine.create_package(content, source, confidence, sharing_level)
    return {"package_id": pkg.package_id, "confidence": pkg.confidence}


@router.post("/intelx/exchange/partners")
async def register_partner(name: str, stix_version: str = "2.1",
                           taxii_endpoint: str = "", authentication: str = "api_key",
                           trust_level: float = 0.5):
    """Register an exchange partner."""
    partner = engine.register_partner(name, stix_version, taxii_endpoint, authentication, trust_level)
    return {"partner_id": partner.partner_id, "name": partner.name, "trust_level": partner.trust_level}


@router.post("/intelx/exchange/exchange")
async def exchange(source_partner_id: str, target_partner_id: str, package_ids: list[str]):
    """Exchange intelligence packages."""
    exchange = engine.exchange(source_partner_id, target_partner_id, package_ids)
    return {
        "exchange_id": exchange.exchange_id,
        "package_count": exchange.package_count,
        "status": exchange.status,
    }


@router.get("/intelx/exchange/stix/{package_id}")
async def export_stix(package_id: str):
    """Export a package in STIX format."""
    return engine.export_stix(package_id)


@router.get("/intelx/exchange/packages")
async def get_packages(sharing_level: str | None = None):
    """Get packages."""
    return {"packages": engine.get_packages(sharing_level)}


@router.get("/intelx/exchange/report")
async def exchange_report():
    """Get exchange protocol report."""
    return engine.get_report()
