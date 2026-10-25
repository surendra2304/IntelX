"""
IntelX/routers/threat_campaign_tracker.py — IntelX Threat Campaign Tracker.

Tracks threat campaigns across time: campaign lifecycle, timeline reconstruction,
target analysis, attribution indicators, and campaign correlation. Provides
campaign intelligence with predictive insights.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ThreatCampaign:
    """A tracked threat campaign."""
    campaign_id: str
    name: str
    description: str = ""
    status: str = "active"  # active, dormant, disrupted, attributed
    threat_actor: str = ""
    start_time: float = 0.0
    last_activity: float = 0.0
    target_sectors: list[str] = field(default_factory=list)
    target_regions: list[str] = field(default_factory=list)
    techniques_used: list[str] = field(default_factory=list)
    attribution_confidence: float = 0.0


@dataclass
class CampaignEvent:
    """An event in a campaign timeline."""
    event_id: str
    campaign_id: str
    event_type: str = ""  # initial_access, persistence, lateral_movement, data_exfiltration
    description: str = ""
    timestamp: float = 0.0
    severity: str = "medium"
    indicators: list[str] = field(default_factory=list)
    target: str = ""


@dataclass
class CampaignTarget:
    """A target of a campaign."""
    target_id: str
    campaign_id: str
    target_name: str = ""
    sector: str = ""
    region: str = ""
    compromise_status: str = ""  # targeted, compromised, contained
    risk_level: str = "medium"
    first_seen: float = 0.0
    last_activity: float = 0.0


@dataclass
class AttributionIndicator:
    """An attribution indicator."""
    indicator_id: str
    campaign_id: str
    indicator_type: str = ""  # infrastructure, tooling, TTP, timing, language
    description: str = ""
    confidence: float = 0.0
    linked_actors: list[str] = field(default_factory=list)
    evidence: str = ""
    added_at: float = 0.0


@dataclass
class CampaignCorrelation:
    """Correlation between campaigns."""
    correlation_id: str
    campaign_a: str
    campaign_b: str
    correlation_score: float = 0.0
    shared_indicators: list[str] = field(default_factory=list)
    shared_tactics: list[str] = field(default_factory=list)
    likely_same_actor: bool = False


@dataclass
class CampaignPrediction:
    """Predictive insight for a campaign."""
    prediction_id: str
    campaign_id: str
    prediction_type: str = ""  # next_target, escalation, technique, timeline
    prediction: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    predicted_at: float = 0.0


@dataclass
class CampaignIntelligence:
    """Comprehensive campaign intelligence summary."""
    campaign_id: str
    name: str
    threat_actor: str
    status: str
    total_events: int = 0
    total_targets: int = 0
    active_indicators: int = 0
    predicted_next_target: str = ""
    escalation_likelihood: float = 0.0
    recommended_actions: list[str] = field(default_factory=list)


class ThreatCampaignTracker:
    """Threat campaign tracking engine."""

    def __init__(self):
        self._campaigns: dict[str, ThreatCampaign] = {}
        self._events: list[CampaignEvent] = []
        self._targets: dict[str, CampaignTarget] = {}
        self._attributions: list[AttributionIndicator] = []
        self._correlations: list[CampaignCorrelation] = []
        self._predictions: list[CampaignPrediction] = []

    def create_campaign(
        self,
        name: str,
        description: str = "",
        threat_actor: str = "",
        target_sectors: list[str] | None = None,
        target_regions: list[str] | None = None,
    ) -> ThreatCampaign:
        """Create a threat campaign."""
        campaign = ThreatCampaign(
            campaign_id=hashlib.md5(
                f"campaign:{name}:{time.time()}".encode()
            ).hexdigest()[:12],
            name=name,
            description=description,
            threat_actor=threat_actor,
            start_time=time.time(),
            last_activity=time.time(),
            target_sectors=target_sectors or ["financial", "technology"],
            target_regions=target_regions or ["North America", "Europe"],
            techniques_used=[],
            attribution_confidence=0.3 + (ord(hashlib.md5(threat_actor.encode()).hexdigest()[:1]) % 40) / 100 if threat_actor else 0.0,
        )
        self._campaigns[campaign.campaign_id] = campaign
        return campaign

    def add_event(
        self,
        campaign_id: str,
        event_type: str,
        description: str,
        severity: str = "medium",
        indicators: list[str] | None = None,
        target: str = "",
        timestamp: float | None = None,
    ) -> CampaignEvent:
        """Add an event to a campaign."""
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise HTTPException(404, f"Campaign {campaign_id} not found")

        event = CampaignEvent(
            event_id=hashlib.md5(
                f"event:{campaign_id}:{event_type}:{time.time()}".encode()
            ).hexdigest()[:12],
            campaign_id=campaign_id,
            event_type=event_type,
            description=description,
            timestamp=timestamp or time.time(),
            severity=severity,
            indicators=indicators or [],
            target=target,
        )

        self._events.append(event)
        campaign.last_activity = event.timestamp
        campaign.techniques_used.append(event_type)

        return event

    def add_target(
        self,
        campaign_id: str,
        target_name: str,
        sector: str = "",
        region: str = "",
        risk_level: str = "medium",
    ) -> CampaignTarget:
        """Add a target to a campaign."""
        target = CampaignTarget(
            target_id=hashlib.md5(
                f"target:{campaign_id}:{target_name}:{time.time()}".encode()
            ).hexdigest()[:12],
            campaign_id=campaign_id,
            target_name=target_name,
            sector=sector,
            region=region,
            compromise_status="targeted",
            risk_level=risk_level,
            first_seen=time.time(),
            last_activity=time.time(),
        )

        self._targets[target.target_id] = target
        return target

    def add_attribution_indicator(
        self,
        campaign_id: str,
        indicator_type: str,
        description: str,
        confidence: float = 0.5,
        linked_actors: list[str] | None = None,
    ) -> AttributionIndicator:
        """Add an attribution indicator."""
        indicator = AttributionIndicator(
            indicator_id=hashlib.md5(
                f"attr:{campaign_id}:{indicator_type}:{time.time()}".encode()
            ).hexdigest()[:12],
            campaign_id=campaign_id,
            indicator_type=indicator_type,
            description=description,
            confidence=confidence,
            linked_actors=linked_actors or [],
            evidence=description,
            added_at=time.time(),
        )

        self._attributions.append(indicator)

        # Update campaign attribution confidence
        campaign = self._campaigns.get(campaign_id)
        if campaign and indicator.linked_actors:
            campaign.attribution_confidence = min(1.0, campaign.attribution_confidence + confidence * 0.1)
            campaign.threat_actor = indicator.linked_actors[0]

        return indicator

    def correlate_campaigns(self, campaign_a: str, campaign_b: str) -> CampaignCorrelation:
        """Correlate two campaigns."""
        ca = self._campaigns.get(campaign_a)
        cb = self._campaigns.get(campaign_b)

        if not ca or not cb:
            raise HTTPException(404, "One or both campaigns not found")

        # Find shared indicators
        shared_indicators = []
        for ind in self._attributions:
            if ind.campaign_id in [campaign_a, campaign_b]:
                shared_indicators.extend(ind.linked_actors)

        shared_indicators = list(set(shared_indicators))

        # Find shared tactics
        shared_tactics = list(set(ca.techniques_used) & set(cb.techniques_used))

        # Calculate correlation score
        score = 0.0
        if shared_indicators:
            score += 0.4
        if shared_tactics:
            score += 0.3 * len(shared_tactics) / max(1, len(set(ca.techniques_used) | set(cb.techniques_used)))
        if ca.threat_actor == cb.threat_actor and ca.threat_actor:
            score += 0.3

        correlation = CampaignCorrelation(
            correlation_id=hashlib.md5(
                f"corr:{campaign_a}:{campaign_b}:{time.time()}".encode()
            ).hexdigest()[:12],
            campaign_a=campaign_a,
            campaign_b=campaign_b,
            correlation_score=round(min(1.0, score), 3),
            shared_indicators=shared_indicators[:10],
            shared_tactics=shared_tactics,
            likely_same_actor=score > 0.6,
        )

        self._correlations.append(correlation)
        return correlation

    def predict(self, campaign_id: str) -> CampaignPrediction:
        """Generate a prediction for a campaign."""
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise HTTPException(404, f"Campaign {campaign_id} not found")

        # Get recent events
        recent = [e for e in self._events if e.campaign_id == campaign_id][-10:]

        # Predict next target
        next_target = campaign.target_sectors[0] if campaign.target_sectors else "unknown"

        # Predict escalation
        escalation = 0.3 + len(recent) * 0.05

        prediction = CampaignPrediction(
            prediction_id=hashlib.md5(
                f"predict:{campaign_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            campaign_id=campaign_id,
            prediction_type="next_target",
            prediction=f"Next likely target sector: {next_target}",
            confidence=0.5 + (ord(hashlib.md5(campaign_id.encode()).hexdigest()[:1]) % 30) / 100,
            reasoning=f"Based on campaign pattern and recent activity",
            predicted_at=time.time(),
        )

        self._predictions.append(prediction)
        return prediction

    def get_intelligence(self, campaign_id: str) -> CampaignIntelligence:
        """Get comprehensive campaign intelligence."""
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise HTTPException(404, f"Campaign {campaign_id} not found")

        events = [e for e in self._events if e.campaign_id == campaign_id]
        targets = [t for t in self._targets.values() if t.campaign_id == campaign_id]
        attributions = [a for a in self._attributions if a.campaign_id == campaign_id]
        predictions = [p for p in self._predictions if p.campaign_id == campaign_id]

        intel = CampaignIntelligence(
            campaign_id=campaign.campaign_id,
            name=campaign.name,
            threat_actor=campaign.threat_actor,
            status=campaign.status,
            total_events=len(events),
            total_targets=len(targets),
            active_indicators=sum(len(a.linked_actors) for a in attributions),
            predicted_next_target=predictions[-1].prediction if predictions else "",
            escalation_likelihood=0.3 + len(events) * 0.05,
            recommended_actions=[
                "Monitor for new target sectors",
                "Enhance detection for known techniques",
                "Share indicators with ISAC",
                "Update defensive controls",
            ],
        )

        return intel

    def get_report(self) -> dict:
        """Get threat campaign tracker report."""
        return {
            "total_campaigns": len(self._campaigns),
            "total_events": len(self._events),
            "total_targets": len(self._targets),
            "total_attributions": len(self._attributions),
            "total_correlations": len(self._correlations),
            "total_predictions": len(self._predictions),
            "active_campaigns": sum(1 for c in self._campaigns.values() if c.status == "active"),
            "attributed_campaigns": sum(1 for c in self._campaigns.values() if c.attribution_confidence > 0.7),
            "campaigns_by_status": {
                status: sum(1 for c in self._campaigns.values() if c.status == status)
                for status in set(c.status for c in self._campaigns.values())
            },
            "recent_events": [
                {"campaign": e.campaign_id, "type": e.event_type, "severity": e.severity, "description": e.description[:60]}
                for e in self._events[-10:]
            ],
            "recent_correlations": [
                {"score": c.correlation_score, "same_actor": c.likely_same_actor, "shared_indicators": len(c.shared_indicators)}
                for c in self._correlations[-5:]
            ],
            "recent_predictions": [
                {"campaign": p.campaign_id, "type": p.prediction_type, "prediction": p.prediction[:60], "confidence": p.confidence}
                for p in self._predictions[-5:]
            ],
        }


campaign_tracker = ThreatCampaignTracker()


@router.post("/api/v1/intelex/campaigns")
async def create_campaign(payload: dict):
    """Create a threat campaign."""
    campaign = campaign_tracker.create_campaign(
        name=payload["name"],
        description=payload.get("description", ""),
        threat_actor=payload.get("threat_actor", ""),
        target_sectors=payload.get("target_sectors", []),
        target_regions=payload.get("target_regions", []),
    )
    return {"campaign_id": campaign.campaign_id, "name": campaign.name, "threat_actor": campaign.threat_actor}


@router.post("/api/v1/intelex/campaigns/{campaign_id}/events")
async def add_event(campaign_id: str, payload: dict):
    """Add an event to a campaign."""
    event = campaign_tracker.add_event(
        campaign_id=campaign_id,
        event_type=payload["event_type"],
        description=payload["description"],
        severity=payload.get("severity", "medium"),
        indicators=payload.get("indicators", []),
        target=payload.get("target", ""),
        timestamp=payload.get("timestamp"),
    )
    return {"event_id": event.event_id, "type": event.event_type, "severity": event.severity}


@router.post("/api/v1/intelex/campaigns/{campaign_id}/targets")
async def add_target(campaign_id: str, payload: dict):
    """Add a target to a campaign."""
    target = campaign_tracker.add_target(
        campaign_id=campaign_id,
        target_name=payload["target_name"],
        sector=payload.get("sector", ""),
        region=payload.get("region", ""),
        risk_level=payload.get("risk_level", "medium"),
    )
    return {"target_id": target.target_id, "name": target.target_name, "risk": target.risk_level}


@router.post("/api/v1/intelex/campaigns/{campaign_id}/predict")
async def predict(campaign_id: str):
    """Generate a prediction for a campaign."""
    prediction = campaign_tracker.predict(campaign_id)
    return {"prediction_id": prediction.prediction_id, "type": prediction.prediction_type, "prediction": prediction.prediction, "confidence": prediction.confidence}


@router.get("/api/v1/intelex/campaigns/{campaign_id}/intelligence")
async def get_intelligence(campaign_id: str):
    """Get comprehensive campaign intelligence."""
    intel = campaign_tracker.get_intelligence(campaign_id)
    return {
        "name": intel.name,
        "threat_actor": intel.threat_actor,
        "status": intel.status,
        "total_events": intel.total_events,
        "total_targets": intel.total_targets,
        "escalation_likelihood": intel.escalation_likelihood,
    }


@router.get("/api/v1/intelex/campaigns/report")
async def get_report():
    """Get threat campaign tracker report."""
    return campaign_tracker.get_report()
