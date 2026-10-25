"""
IntelX/routers/threat_forecast_engine.py — IntelX Threat Forecast Engine.

Predict future threat landscape, emerging attack vectors, threat
trend analysis, and forecast calibration.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ThreatForecast:
    """A threat forecast."""
    forecast_id: str
    threat_type: str  # malware, ransomware, phishing, etc.
    predicted_severity: float = 0.0  # 0-1
    predicted_intensity: float = 0.0  # 0-1
    timeframe_days: int = 30
    confidence: float = 0.5
    indicators: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class EmergingVector:
    """An emerging attack vector."""
    vector_id: str
    name: str
    description: str
    risk_level: str = "medium"
    exploitability: float = 0.5
    patch_availability: str = "unknown"
    detected_at: float = field(default_factory=time.time)


@dataclass
class ForecastTrend:
    """A threat trend over time."""
    trend_id: str
    threat_type: str
    trend_direction: str = "increasing"  # increasing, decreasing, stable
    growth_rate: float = 0.0
    data_points: list[dict] = field(default_factory=list)


class ThreatForecastEngine:
    """Engine for predicting future threat landscape."""

    def __init__(self) -> None:
        self._forecasts: dict[str, ThreatForecast] = {}
        self._vectors: dict[str, EmergingVector] = {}
        self._trends: dict[str, ForecastTrend] = {}

    def generate_forecast(self, threat_type: str, indicators: list[str] | None = None,
                          timeframe_days: int = 30) -> ThreatForecast:
        """Generate a threat forecast."""
        forecast_id = f"tf_{uuid.uuid4().hex[:12]}"
        severity = hash(threat_type + time.strftime("%Y%m")) % 100 / 100.0
        intensity = severity * 0.8 + 0.1
        forecast = ThreatForecast(
            forecast_id=forecast_id, threat_type=threat_type,
            predicted_severity=severity, predicted_intensity=intensity,
            timeframe_days=timeframe_days, confidence=0.7,
            indicators=indicators or [],
        )
        self._forecasts[forecast_id] = forecast
        return forecast

    def register_emerging_vector(self, name: str, description: str,
                                 risk_level: str = "medium") -> EmergingVector:
        """Register an emerging attack vector."""
        vector_id = f"ev_{uuid.uuid4().hex[:12]}"
        vector = EmergingVector(
            vector_id=vector_id, name=name, description=description,
            risk_level=risk_level,
            exploitability=0.5 if risk_level == "medium" else 0.8 if risk_level == "high" else 0.3,
        )
        self._vectors[vector_id] = vector
        return vector

    def record_trend(self, threat_type: str, direction: str = "increasing",
                     growth_rate: float = 0.0, data_point: dict | None = None) -> ForecastTrend:
        """Record a threat trend."""
        trend_id = f"trend_{uuid.uuid4().hex[:12]}"
        trend = ForecastTrend(
            trend_id=trend_id, threat_type=threat_type,
            trend_direction=direction, growth_rate=growth_rate,
        )
        if data_point:
            trend.data_points.append(data_point)
        self._trends[trend_id] = trend
        return trend

    def get_forecasts(self, threat_type: str | None = None) -> list[dict[str, Any]]:
        """Get forecasts."""
        forecasts = list(self._forecasts.values())
        if threat_type:
            forecasts = [f for f in forecasts if f.threat_type == threat_type]
        return [
            {
                "forecast_id": f.forecast_id,
                "threat_type": f.threat_type,
                "predicted_severity": f.predicted_severity,
                "confidence": f.confidence,
                "timeframe_days": f.timeframe_days,
            }
            for f in forecasts
        ]

    def get_vectors(self) -> list[dict[str, Any]]:
        """Get emerging vectors."""
        return [
            {
                "vector_id": v.vector_id,
                "name": v.name,
                "risk_level": v.risk_level,
                "exploitability": v.exploitability,
            }
            for v in self._vectors.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_forecasts": len(self._forecasts),
            "total_vectors": len(self._vectors),
            "total_trends": len(self._trends),
            "engine_status": "operational",
        }


engine = ThreatForecastEngine()


@router.post("/intelex/forecast/generate")
async def generate_forecast(threat_type: str, indicators: list[str] | None = None, timeframe_days: int = 30):
    """Generate a threat forecast."""
    forecast = engine.generate_forecast(threat_type, indicators, timeframe_days)
    return {
        "forecast_id": forecast.forecast_id,
        "threat_type": forecast.threat_type,
        "predicted_severity": forecast.predicted_severity,
        "confidence": forecast.confidence,
    }


@router.post("/intelex/forecast/vectors")
async def register_vector(name: str, description: str, risk_level: str = "medium"):
    """Register an emerging attack vector."""
    vector = engine.register_emerging_vector(name, description, risk_level)
    return {"vector_id": vector.vector_id, "name": vector.name, "risk_level": vector.risk_level}


@router.get("/intelex/forecast/forecasts")
async def get_forecasts(threat_type: str | None = None):
    """Get threat forecasts."""
    return {"forecasts": engine.get_forecasts(threat_type)}


@router.get("/intelex/forecast/vectors")
async def get_vectors():
    """Get emerging vectors."""
    return {"vectors": engine.get_vectors()}


@router.get("/intelex/forecast/report")
async def forecast_report():
    """Get threat forecast report."""
    return engine.get_report()
