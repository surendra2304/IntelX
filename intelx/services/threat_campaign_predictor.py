"""
IntelX/intelx/services/threat_campaign_predictor.py — IntelX Threat Campaign Predictor.

Threat campaign forecasting, attack timeline prediction, campaign progression modeling,
and strategic threat anticipation.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class CampaignPhase:
    """A phase in a threat campaign."""
    phase_id: str
    name: str
    description: str = ""
    start_probability: float = 0.0
    duration_estimate: float = 0.0
    ttp_indicators: list[str] = field(default_factory=list)


@dataclass
class CampaignForecast:
    """A forecast of a threat campaign."""
    forecast_id: str
    actor: str
    current_phase: str = ""
    predicted_phases: list[str] = field(default_factory=list)
    probability_timeline: list[dict] = field(default_factory=list)
    confidence: float = 0.5
    created_at: float = field(default_factory=time.time)


@dataclass
class StrategicAssessment:
    """A strategic threat assessment."""
    assessment_id: str
    threat_level: str = "medium"
    risk_score: float = 0.0
    likely_targets: list[str] = field(default_factory=list)
    timeline: str = ""
    recommendations: list[str] = field(default_factory=list)


class ThreatCampaignPredictor:
    """Engine for threat campaign prediction."""

    def __init__(self) -> None:
        self._phases: dict[str, CampaignPhase] = {}
        self._forecasts: list[CampaignForecast] = []
        self._assessments: list[StrategicAssessment] = []

    def add_phase(self, name: str, description: str = "",
                  start_probability: float = 0.0,
                  duration_estimate: float = 0.0,
                  ttp_indicators: list[str] | None = None) -> CampaignPhase:
        """Add a campaign phase."""
        phase_id = f"ph_{uuid.uuid4().hex[:12]}"
        phase = CampaignPhase(
            phase_id=phase_id, name=name, description=description,
            start_probability=start_probability,
            duration_estimate=duration_estimate,
            ttp_indicators=ttp_indicators or [],
        )
        self._phases[phase_id] = phase
        return phase

    def forecast_campaign(self, actor: str, current_phase: str = "") -> CampaignForecast:
        """Forecast a threat campaign."""
        forecast_id = f"fc_{uuid.uuid4().hex[:12]}"
        forecast = CampaignForecast(
            forecast_id=forecast_id, actor=actor,
            current_phase=current_phase,
        )

        forecast.predicted_phases = [p.name for p in self._phases.values()]

        # Build probability timeline
        for phase in self._phases.values():
            forecast.probability_timeline.append({
                "phase": phase.name,
                "probability": phase.start_probability,
                "duration": phase.duration_estimate,
            })

        forecast.confidence = min(0.9, len(forecast.predicted_phases) * 0.15)

        self._forecasts.append(forecast)
        return forecast

    def assess_strategic_threat(self, threat_level: str = "medium") -> StrategicAssessment:
        """Assess strategic threat level."""
        assessment_id = f"sa_{uuid.uuid4().hex[:12]}"
        assessment = StrategicAssessment(
            assessment_id=assessment_id, threat_level=threat_level,
        )

        threat_scores = {"low": 25.0, "medium": 50.0, "high": 75.0, "critical": 95.0}
        assessment.risk_score = threat_scores.get(threat_level, 50.0)

        if threat_level in ("high", "critical"):
            assessment.likely_targets = ["financial", "healthcare", "government", "critical infrastructure"]
            assessment.timeline = "Near-term (0-3 months)"
            assessment.recommendations = [
                "Increase monitoring of critical assets",
                "Review access controls",
                "Conduct threat hunting",
                "Update incident response plan",
            ]
        else:
            assessment.likely_targets = ["corporate", "technology"]
            assessment.timeline = "Medium-term (3-12 months)"
            assessment.recommendations = [
                "Maintain standard monitoring",
                "Regular security assessments",
            ]

        self._assessments.append(assessment)
        return assessment

    def get_phases(self) -> list[dict[str, Any]]:
        """Get campaign phases."""
        return [
            {"name": p.name, "description": p.description[:60],
             "probability": p.start_probability, "ttp_count": len(p.ttp_indicators)}
            for p in self._phases.values()
        ]

    def get_forecasts(self, actor: str | None = None) -> list[dict[str, Any]]:
        """Get campaign forecasts."""
        forecasts = self._forecasts
        if actor:
            forecasts = [f for f in forecasts if f.actor == actor]
        return [
            {"actor": f.actor, "current_phase": f.current_phase,
             "phase_count": len(f.predicted_phases), "confidence": f.confidence}
            for f in forecasts
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_phases": len(self._phases),
            "total_forecasts": len(self._forecasts),
            "total_assessments": len(self._assessments),
            "engine_status": "operational",
        }


engine = ThreatCampaignPredictor()


@router.post("/intelx/campaign/phases")
async def add_phase(name: str, description: str = "", start_probability: float = 0.0,
                    duration_estimate: float = 0.0, ttp_indicators: list[str] | None = None):
    """Add a campaign phase."""
    phase = engine.add_phase(name, description, start_probability, duration_estimate, ttp_indicators)
    return {"phase_id": phase.phase_id, "name": phase.name}


@router.post("/intelx/campaign/forecast")
async def forecast_campaign(actor: str, current_phase: str = ""):
    """Forecast a threat campaign."""
    forecast = engine.forecast_campaign(actor, current_phase)
    return {
        "actor": actor,
        "current_phase": forecast.current_phase,
        "phase_count": len(forecast.predicted_phases),
        "confidence": forecast.confidence,
    }


@router.post("/intelx/campaign/assess")
async def assess_strategic_threat(threat_level: str = "medium"):
    """Assess strategic threat level."""
    assessment = engine.assess_strategic_threat(threat_level)
    return {
        "threat_level": assessment.threat_level,
        "risk_score": assessment.risk_score,
        "timeline": assessment.timeline,
        "recommendations": assessment.recommendations,
    }


@router.get("/intelx/campaign/phases")
async def get_phases():
    """Get campaign phases."""
    return {"phases": engine.get_phases()}


@router.get("/intelx/campaign/forecasts")
async def get_forecasts(actor: str | None = None):
    """Get campaign forecasts."""
    return {"forecasts": engine.get_forecasts(actor)}


@router.get("/intelx/campaign/report")
async def campaign_report():
    """Get campaign predictor report."""
    return engine.get_report()
