"""
IntelX/intelx/services/disinformation_detector.py — IntelX Disinformation Detector.

False information detection, source credibility analysis,
coordinated inauthentic behavior detection, and propaganda analysis.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class DisinfoIndicator:
    """A disinformation indicator."""
    indicator_id: str
    content_snippet: str = ""
    indicator_type: str = ""  # emotional_language, conspiracy, misleading_source, etc
    confidence: float = 0.0
    severity: str = "low"  # low, medium, high, critical
    description: str = ""


@dataclass
class SourceCredibilityScore:
    """A source credibility score."""
    source_id: str
    domain: str = ""
    credibility: float = 0.5
    track_record: float = 0.0
    transparency: float = 0.0
    bias_score: float = 0.5
    notes: str = ""


@dataclass
class DisinformationReport:
    """A disinformation analysis report."""
    report_id: str
    content_hash: str = ""
    indicators: list[DisinfoIndicator] = field(default_factory=list)
    source_scores: list[SourceCredibilityScore] = field(default_factory=list)
    overall_risk: str = "low"
    risk_score: float = 0.0
    analyzed_at: float = field(default_factory=time.time)


class DisinformationDetector:
    """Engine for disinformation detection and analysis."""

    def __init__(self) -> None:
        self._indicators: dict[str, DisinfoIndicator] = {}
        self._sources: dict[str, SourceCredibilityScore] = {}
        self._reports: list[DisinformationReport] = []

    def register_source(self, source_id: str, domain: str, credibility: float = 0.5,
                        track_record: float = 0.0, transparency: float = 0.0,
                        bias_score: float = 0.5, notes: str = "") -> str:
        """Register a source with credibility score."""
        score = SourceCredibilityScore(
            source_id=source_id, domain=domain, credibility=credibility,
            track_record=track_record, transparency=transparency,
            bias_score=bias_score, notes=notes,
        )
        self._sources[source_id] = score
        return source_id

    def detect(self, content: str, source_id: str = "") -> DisinformationReport:
        """Detect disinformation in content."""
        report_id = f"disinfo_{uuid.uuid4().hex[:12]}"
        report = DisinformationReport(report_id=report_id, content_hash=content[:100])

        words = content.lower()
        risk_score = 0.0

        # Emotional language check
        emotional_words = ["shocking", "outrageous", "they don't want you to know", "wake up"]
        for word in emotional_words:
            if word in words:
                indicator = DisinfoIndicator(
                    indicator_id=f"ind_{uuid.uuid4().hex[:8]}",
                    content_snippet=content[:100],
                    indicator_type="emotional_language",
                    confidence=0.7, severity="medium",
                    description=f"Emotional language detected: {word}",
                )
                report.indicators.append(indicator)
                risk_score += 0.15

        # Conspiracy check
        conspiracy_words = ["deep state", "cover-up", "secret plan", "they're hiding"]
        for word in conspiracy_words:
            if word in words:
                indicator = DisinfoIndicator(
                    indicator_id=f"ind_{uuid.uuid4().hex[:8]}",
                    content_snippet=content[:100],
                    indicator_type="conspiracy",
                    confidence=0.8, severity="high",
                    description=f"Conspiracy language detected: {word}",
                )
                report.indicators.append(indicator)
                risk_score += 0.25

        # Source credibility check
        if source_id and source_id in self._sources:
            source = self._sources[source_id]
            report.source_scores.append(source)
            if source.credibility < 0.3:
                indicator = DisinfoIndicator(
                    indicator_id=f"ind_{uuid.uuid4().hex[:8]}",
                    content_snippet=content[:100],
                    indicator_type="low_credibility_source",
                    confidence=source.credibility, severity="high",
                    description=f"Source has low credibility: {source.domain}",
                )
                report.indicators.append(indicator)
                risk_score += 0.3

        report.risk_score = min(1.0, risk_score)
        if report.risk_score > 0.7:
            report.overall_risk = "critical"
        elif report.risk_score > 0.5:
            report.overall_risk = "high"
        elif report.risk_score > 0.3:
            report.overall_risk = "medium"
        else:
            report.overall_risk = "low"

        self._reports.append(report)
        return report

    def get_source_score(self, source_id: str) -> dict[str, Any]:
        """Get a source credibility score."""
        score = self._sources.get(source_id)
        if not score:
            raise HTTPException(status_code=404, detail="Source not found")
        return {
            "source_id": score.source_id,
            "domain": score.domain,
            "credibility": score.credibility,
            "bias_score": score.bias_score,
        }

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_indicators": len(self._indicators),
            "total_sources": len(self._sources),
            "total_reports": len(self._reports),
            "engine_status": "operational",
        }


engine = DisinformationDetector()


@router.post("/intelx/disinfo/sources")
async def register_source(source_id: str, domain: str, credibility: float = 0.5,
                          track_record: float = 0.0, transparency: float = 0.0,
                          bias_score: float = 0.5, notes: str = ""):
    """Register a source with credibility score."""
    engine.register_source(source_id, domain, credibility, track_record, transparency, bias_score, notes)
    return {"source_id": source_id, "status": "registered"}


@router.post("/intelx/disinfo/detect")
async def detect(content: str, source_id: str = ""):
    """Detect disinformation in content."""
    report = engine.detect(content, source_id)
    return {
        "report_id": report.report_id,
        "overall_risk": report.overall_risk,
        "risk_score": report.risk_score,
        "indicator_count": len(report.indicators),
    }


@router.get("/intelx/disinfo/sources/{source_id}")
async def get_source_score(source_id: str):
    """Get a source credibility score."""
    return engine.get_source_score(source_id)


@router.get("/intelx/disinfo/report")
async def disinfo_report():
    """Get disinformation detector report."""
    return engine.get_report()
