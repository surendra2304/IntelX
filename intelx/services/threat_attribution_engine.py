"""
IntelX/intelx/services/threat_attribution_engine.py — IntelX Threat Attribution Engine.

Threat actor attribution, infrastructure fingerprinting, TTP matching,
and confidence-scored attribution analysis.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ActorProfile:
    """A threat actor profile."""
    actor_id: str
    aliases: list[str] = field(default_factory=list)
    ttps: list[str] = field(default_factory=list)
    motivation: str = ""  # financial, political, ideological, unknown
    sophistication: str = "intermediate"  # low, intermediate, advanced, expert
    first_seen: float = 0.0
    last_seen: float = 0.0
    target_sectors: list[str] = field(default_factory=list)


@dataclass
class AttributionEvidence:
    """Evidence supporting an attribution."""
    evidence_id: str
    description: str
    evidence_type: str = ""  # infrastructure, TTP, tooling, victim, timing
    confidence: float = 0.0
    source: str = ""


@dataclass
class AttributionResult:
    """Result of a threat attribution analysis."""
    result_id: str
    target_indicator: str
    attributed_actor: str = ""
    confidence: float = 0.0
    evidence: list[AttributionEvidence] = field(default_factory=list)
    alternative_actors: list[str] = field(default_factory=list)
    analyzed_at: float = field(default_factory=time.time)


class ThreatAttributionEngine:
    """Engine for threat actor attribution."""

    def __init__(self) -> None:
        self._actors: dict[str, ActorProfile] = {}
        self._results: list[AttributionResult] = []

    def register_actor(self, actor_id: str, aliases: list[str] = None,
                       ttps: list[str] = None, motivation: str = "",
                       sophistication: str = "intermediate",
                       target_sectors: list[str] = None) -> ActorProfile:
        """Register a threat actor profile."""
        actor = ActorProfile(
            actor_id=actor_id, aliases=aliases or [], ttps=ttps or [],
            motivation=motivation, sophistication=sophistication,
            target_sectors=target_sectors or [],
        )
        actor.first_seen = time.time()
        self._actors[actor_id] = actor
        return actor

    def attribute(self, indicator: str, description: str = "",
                 evidence_type: str = "infrastructure",
                 confidence: float = 0.5,
                 source: str = "") -> AttributionResult:
        """Attribute an indicator to a threat actor."""
        result_id = f"attr_{uuid.uuid4().hex[:12]}"
        result = AttributionResult(result_id=result_id, target_indicator=indicator)

        # Find matching actors
        for actor in self._actors.values():
            if any(alias.lower() in indicator.lower() for alias in actor.aliases):
                result.attributed_actor = actor.actor_id
                result.confidence = max(result.confidence, confidence * 0.8)
                break

        evidence = AttributionEvidence(
            evidence_id=f"ev_{uuid.uuid4().hex[:8]}",
            description=description, evidence_type=evidence_type,
            confidence=confidence, source=source,
        )
        result.evidence.append(evidence)

        # Suggest alternative actors
        if result.confidence < 0.7:
            alternatives = list(self._actors.keys())[:2]
            result.alternative_actors = alternatives

        self._results.append(result)
        return result

    def get_actor_profile(self, actor_id: str) -> dict[str, Any]:
        """Get an actor profile."""
        actor = self._actors.get(actor_id)
        if not actor:
            raise HTTPException(status_code=404, detail="Actor not found")
        return {
            "actor_id": actor.actor_id,
            "aliases": actor.aliases,
            "ttp_count": len(actor.ttps),
            "motivation": actor.motivation,
            "sophistication": actor.sophistication,
            "target_sectors": actor.target_sectors,
        }

    def get_attribution_results(self, confidence_threshold: float = 0.0) -> list[dict[str, Any]]:
        """Get attribution results."""
        return [
            {
                "indicator": r.target_indicator,
                "actor": r.attributed_actor,
                "confidence": r.confidence,
                "evidence_count": len(r.evidence),
            }
            for r in self._results if r.confidence >= confidence_threshold
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_actors": len(self._actors),
            "total_results": len(self._results),
            "high_confidence": sum(1 for r in self._results if r.confidence > 0.7),
            "engine_status": "operational",
        }


engine = ThreatAttributionEngine()


@router.post("/intelx/attribution/actors")
async def register_actor(actor_id: str, aliases: list[str] | None = None,
                         ttps: list[str] | None = None, motivation: str = "",
                         sophistication: str = "intermediate",
                         target_sectors: list[str] | None = None):
    """Register a threat actor."""
    engine.register_actor(actor_id, aliases, ttps, motivation, sophistication, target_sectors)
    return {"actor_id": actor_id, "status": "registered"}


@router.post("/intelx/attribution/analyze")
async def attribute(indicator: str, description: str = "", evidence_type: str = "infrastructure",
                    confidence: float = 0.5, source: str = ""):
    """Attribute an indicator to a threat actor."""
    result = engine.attribute(indicator, description, evidence_type, confidence, source)
    return {
        "result_id": result.result_id,
        "attributed_actor": result.attributed_actor,
        "confidence": result.confidence,
        "evidence_count": len(result.evidence),
    }


@router.get("/intelx/attribution/actors/{actor_id}")
async def get_actor_profile(actor_id: str):
    """Get an actor profile."""
    return engine.get_actor_profile(actor_id)


@router.get("/intelx/attribution/results")
async def get_results(confidence_threshold: float = 0.0):
    """Get attribution results."""
    return {"results": engine.get_attribution_results(confidence_threshold)}


@router.get("/intelx/attribution/report")
async def attribution_report():
    """Get attribution engine report."""
    return engine.get_report()
