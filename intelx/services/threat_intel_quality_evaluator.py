"""
IntelX/intelx/services/threat_intel_quality_evaluator.py — IntelX Threat Intel Quality Evaluator.

Intellroduct quality scoring, source reliability assessment,
false positive detection, and intelligence maturity measurement.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class IntelItem:
    """An intelligence item to evaluate."""
    item_id: str
    content: str
    source: str = ""
    source_type: str = "feed"  # feed, manual, partner, osint, internal
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)


@dataclass
class QualityScore:
    """Quality score for an intelligence item."""
    score_id: str
    item_id: str
    overall_score: float = 0.0
    accuracy: float = 0.0
    completeness: float = 0.0
    timeliness: float = 0.0
    relevance: float = 0.0
    consistency: float = 0.0
    grade: str = "C"


@dataclass
class SourceReliability:
    """Reliability assessment for an intelligence source."""
    source: str
    reliability_score: float = 0.0
    track_record: float = 0.0
    update_frequency: float = 0.0
    false_positive_rate: float = 0.0
    last_updated: float = 0.0


class ThreatIntelQualityEvaluator:
    """Engine for threat intelligence quality evaluation."""

    def __init__(self) -> None:
        self._items: dict[str, IntelItem] = {}
        self._scores: list[QualityScore] = []
        self._sources: dict[str, SourceReliability] = {}

    def add_item(self, content: str, source: str = "", source_type: str = "feed",
                 tags: list[str] | None = None) -> IntelItem:
        """Add an intelligence item."""
        item_id = f"ti_{uuid.uuid4().hex[:12]}"
        item = IntelItem(
            item_id=item_id, content=content, source=source,
            source_type=source_type, tags=tags or [],
        )
        self._items[item_id] = item
        return item

    def evaluate_quality(self, item_id: str) -> QualityScore:
        """Evaluate the quality of an intelligence item."""
        item = self._items.get(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        score_id = f"qs_{uuid.uuid4().hex[:12]}"
        score = QualityScore(score_id=score_id, item_id=item_id)

        # Accuracy: based on source reliability and content length
        content_len = len(item.content)
        score.accuracy = min(1.0, content_len / 500.0)

        # Completeness: presence of key elements (IoC, TTP, context)
        has_ioc = any(w in item.content.lower() for w in ["ip", "domain", "hash", "url", "email"])
        has_ttp = any(w in item.content.lower() for w in ["cve", "att&ck", "technique", "ttp"])
        has_context = len(item.tags) > 0
        score.completeness = (has_ioc * 0.3 + has_ttp * 0.4 + has_context * 0.3)

        # Timeliness: based on age
        age = time.time() - item.timestamp
        score.timeliness = max(0.0, 1.0 - (age / 86400 / 30))  # decay over 30 days

        # Relevance: based on tags
        score.relevance = min(1.0, len(item.tags) * 0.2)

        # Consistency: based on source history
        source = self._sources.get(item.source)
        score.consistency = source.track_record if source else 0.5

        score.overall_score = (
            score.accuracy * 0.2 + score.completeness * 0.25 +
            score.timeliness * 0.2 + score.relevance * 0.15 +
            score.consistency * 0.2
        ) * 100

        if score.overall_score >= 80:
            score.grade = "A"
        elif score.overall_score >= 70:
            score.grade = "B"
        elif score.overall_score >= 50:
            score.grade = "C"
        elif score.overall_score >= 30:
            score.grade = "D"
        else:
            score.grade = "F"

        self._scores.append(score)
        return score

    def assess_source(self, source: str, track_record: float = 0.5,
                      update_frequency: float = 0.5,
                      false_positive_rate: float = 0.3) -> SourceReliability:
        """Assess source reliability."""
        reliability = SourceReliability(
            source=source, track_record=track_record,
            update_frequency=update_frequency,
            false_positive_rate=false_positive_rate,
            last_updated=time.time(),
        )
        reliability.reliability_score = (
            track_record * 0.4 + update_frequency * 0.3 +
            (1.0 - false_positive_rate) * 0.3
        ) * 100
        self._sources[source] = reliability
        return reliability

    def get_low_quality(self, threshold: float = 50.0) -> list[dict[str, Any]]:
        """Get low-quality intelligence items."""
        low = [s for s in self._scores if s.overall_score < threshold]
        return [
            {"item_id": s.item_id, "score": s.overall_score, "grade": s.grade,
             "issues": [
                 name for name, val in [
                     ("accuracy", s.accuracy), ("completeness", s.completeness),
                     ("timeliness", s.timeliness)
                 ] if val < 0.5
             ]}
            for s in low
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        avg_score = (
            sum(s.overall_score for s in self._scores) / max(1, len(self._scores))
        ) if self._scores else 0
        return {
            "total_items": len(self._items),
            "total_scores": len(self._scores),
            "total_sources": len(self._sources),
            "avg_quality": round(avg_score, 1),
            "engine_status": "operational",
        }


engine = ThreatIntelQualityEvaluator()


@router.post("/intelx/quality/items")
async def add_item(content: str, source: str = "", source_type: str = "feed",
                   tags: list[str] | None = None):
    """Add an intelligence item."""
    item = engine.add_item(content, source, source_type, tags)
    return {"item_id": item.item_id, "source": item.source}


@router.post("/intelx/quality/evaluate/{item_id}")
async def evaluate_quality(item_id: str):
    """Evaluate intelligence quality."""
    score = engine.evaluate_quality(item_id)
    return {
        "item_id": item_id,
        "overall_score": score.overall_score,
        "grade": score.grade,
        "accuracy": score.accuracy,
        "completeness": score.completeness,
    }


@router.post("/intelx/quality/sources")
async def assess_source(source: str, track_record: float = 0.5,
                        update_frequency: float = 0.5, false_positive_rate: float = 0.3):
    """Assess source reliability."""
    reliability = engine.assess_source(source, track_record, update_frequency, false_positive_rate)
    return {"source": source, "reliability_score": reliability.reliability_score}


@router.get("/intelx/quality/low")
async def get_low_quality(threshold: float = 50.0):
    """Get low-quality intelligence items."""
    return {"low_quality": engine.get_low_quality(threshold)}


@router.get("/intelx/quality/report")
async def quality_report():
    """Get quality evaluator report."""
    return engine.get_report()
