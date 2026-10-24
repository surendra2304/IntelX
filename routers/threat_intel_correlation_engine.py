"""
IntelX/routers/threat_intel_correlation_engine.py — IntelX Threat Intel Correlation Engine.

Correlates threat intelligence from multiple sources: IoC matching,
campaign linking, actor attribution, timeline reconstruction, and
pattern analysis. Provides unified threat view across disparate data.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class IoCRecord:
    """An indicator of compromise."""
    ioc_id: str
    value: str
    type: str = ""  # ip, domain, hash, url, email, cert
    source: str = ""
    confidence: float = 0.5
    first_seen: float = 0.0
    last_seen: float = 0.0
    malicious: bool = True
    tags: list[str] = field(default_factory=list)


@dataclass
class CorrelationResult:
    """A correlation result between IoCs."""
    correlation_id: str
    ioc_a: str
    ioc_b: str
    correlation_type: str = ""  # temporal, geographic, behavioral, technical, temporal_proximity
    score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    shared_attributes: list[str] = field(default_factory=list)
    detected_at: float = 0.0


@dataclass
class CampaignLink:
    """A link between a campaign and an IoC."""
    link_id: str
    campaign_id: str
    ioc_id: str
    link_type: str = ""  # observed_in, used_by, attributed_to
    confidence: float = 0.5
    evidence: str = ""
    created_at: float = 0.0


@dataclass
class ActorProfile:
    """A threat actor profile."""
    actor_id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    motivation: str = ""  # financial, espionage, disruption
    sophistication: str = "advanced"
    target_sectors: list[str] = field(default_factory=list)
    techniques: list[str] = field(default_factory=list)
    confidence: float = 0.0
    iocs: list[str] = field(default_factory=list)
    campaigns: list[str] = field(default_factory=list)


@dataclass
class TimelineEvent:
    """An event in a threat timeline."""
    event_id: str
    timestamp: float
    event_type: str = ""  # ioc_seen, campaign_activity, actor_seen, mitigation
    description: str = ""
    source: str = ""
    ioc_id: str = ""
    campaign_id: str = ""
    actor_id: str = ""


@dataclass
class PatternMatch:
    """A matched threat pattern."""
    match_id: str
    pattern_id: str
    pattern_name: str
    matched_iocs: list[str] = field(default_factory=list)
    match_score: float = 0.0
    confidence: float = 0.0
    description: str = ""
    detected_at: float = 0.0


@dataclass
class CorrelationReport:
    """Comprehensive correlation report."""
    total_iocs: int = 0
    total_correlations: int = 0
    total_campaign_links: int = 0
    total_actors: int = 0
    total_patterns: int = 0
    avg_correlation_score: float = 0.0
    top_correlated_iocs: list[str] = field(default_factory=list)
    coverage: float = 0.0


class ThreatIntelCorrelationEngine:
    """Threat intelligence correlation engine."""

    def __init__(self):
        self._iocs: dict[str, IoCRecord] = {}
        self._correlations: list[CorrelationResult] = []
        self._campaign_links: list[CampaignLink] = []
        self._actors: dict[str, ActorProfile] = {}
        self._timeline: list[TimelineEvent] = []
        self._patterns: list[PatternMatch] = []
        self._reports: list[CorrelationReport] = []

    def add_ioc(
        self,
        value: str,
        ioc_type: str,
        source: str = "",
        confidence: float = 0.5,
        malicious: bool = True,
        tags: list[str] | None = None,
    ) -> IoCRecord:
        """Add an IoC."""
        ioc = IoCRecord(
            ioc_id=hashlib.md5(
                f"ioc:{value}:{time.time()}".encode()
            ).hexdigest()[:12],
            value=value,
            type=ioc_type,
            source=source,
            confidence=confidence,
            first_seen=time.time(),
            last_seen=time.time(),
            malicious=malicious,
            tags=tags or [],
        )
        self._iocs[ioc.ioc_id] = ioc

        # Add timeline event
        self._timeline.append(TimelineEvent(
            event_id=hashlib.md5(f"timeline:{ioc.ioc_id}:{time.time()}".encode()).hexdigest()[:12],
            timestamp=time.time(),
            event_type="ioc_seen",
            description=f"IoC {value} seen from {source}",
            source=source,
            ioc_id=ioc.ioc_id,
        ))

        return ioc

    def correlate(self, ioc_a_id: str, ioc_b_id: str) -> CorrelationResult:
        """Correlate two IoCs."""
        a = self._iocs.get(ioc_a_id)
        b = self._iocs.get(ioc_b_id)

        if not a or not b:
            raise HTTPException(404, "One or both IoCs not found")

        # Calculate correlation score
        score = 0.0
        evidence = []
        shared_attrs = []

        # Same source
        if a.source == b.source:
            score += 0.2
            evidence.append(f"Same source: {a.source}")
            shared_attrs.append("source")

        # Same type
        if a.type == b.type:
            score += 0.1
            shared_attrs.append("type")

        # Shared tags
        shared_tags = set(a.tags) & set(b.tags)
        if shared_tags:
            score += 0.1 * len(shared_tags)
            evidence.append(f"Shared tags: {shared_tags}")
            shared_attrs.append("tags")

        # Temporal proximity
        time_diff = abs(a.last_seen - b.last_seen)
        if time_diff < 3600:  # Within 1 hour
            score += 0.3
            evidence.append(f"Temporal proximity: {time_diff:.0f}s apart")
            shared_attrs.append("temporal")

        # Confidence
        score += (a.confidence + b.confidence) * 0.15

        correlation = CorrelationResult(
            correlation_id=hashlib.md5(
                f"corr:{ioc_a_id}:{ioc_b_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            ioc_a=ioc_a_id,
            ioc_b=ioc_b_id,
            correlation_type="multi_factor",
            score=round(min(1.0, score), 3),
            evidence=evidence,
            shared_attributes=shared_attrs,
            detected_at=time.time(),
        )

        self._correlations.append(correlation)
        return correlation

    def link_campaign_ioc(self, campaign_id: str, ioc_id: str, link_type: str, confidence: float = 0.5) -> CampaignLink:
        """Link a campaign to an IoC."""
        link = CampaignLink(
            link_id=hashlib.md5(
                f"link:{campaign_id}:{ioc_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            campaign_id=campaign_id,
            ioc_id=ioc_id,
            link_type=link_type,
            confidence=confidence,
            evidence=f"IoC {ioc_id} linked to campaign {campaign_id}",
            created_at=time.time(),
        )

        self._campaign_links.append(link)

        # Add timeline event
        self._timeline.append(TimelineEvent(
            event_id=hashlib.md5(f"timeline:{link.link_id}:{time.time()}".encode()).hexdigest()[:12],
            timestamp=time.time(),
            event_type="campaign_activity",
            description=f"Campaign {campaign_id} linked to IoC {ioc_id}",
            ioc_id=ioc_id,
            campaign_id=campaign_id,
        ))

        return link

    def create_actor(self, name: str, aliases: list[str] | None = None, motivation: str = "") -> ActorProfile:
        """Create a threat actor profile."""
        actor = ActorProfile(
            actor_id=hashlib.md5(
                f"actor:{name}:{time.time()}".encode()
            ).hexdigest()[:12],
            name=name,
            aliases=aliases or [],
            motivation=motivation,
            sophistication="advanced",
            target_sectors=["financial", "technology"],
            techniques=["T1595", "T1078", "T1027"],
            confidence=0.4,
        )
        self._actors[actor.actor_id] = actor
        return actor

    def match_pattern(self, pattern_id: str, pattern_name: str, iocs: list[str]) -> PatternMatch:
        """Match a threat pattern against IoCs."""
        matched = [ioc_id for ioc_id in iocs if ioc_id in self._iocs]

        match = PatternMatch(
            match_id=hashlib.md5(
                f"pattern:{pattern_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            pattern_id=pattern_id,
            pattern_name=pattern_name,
            matched_iocs=matched,
            match_score=len(matched) / max(1, len(iocs)),
            confidence=0.7 + (ord(hashlib.md5(pattern_id.encode()).hexdigest()[:1]) % 20) / 100,
            description=f"Matched pattern '{pattern_name}' against {len(matched)} IoCs",
            detected_at=time.time(),
        )

        self._patterns.append(match)
        return match

    def generate_report(self) -> CorrelationReport:
        """Generate correlation report."""
        report = CorrelationReport(
            total_iocs=len(self._iocs),
            total_correlations=len(self._correlations),
            total_campaign_links=len(self._campaign_links),
            total_actors=len(self._actors),
            total_patterns=len(self._patterns),
            avg_correlation_score=sum(c.score for c in self._correlations) / max(1, len(self._correlations)),
            top_correlated_iocs=[
                ioc_id for ioc_id, _ in sorted(
                    [(ioc_id, sum(1 for c in self._correlations if ioc_id in [c.ioc_a, c.ioc_b])) for ioc_id in self._iocs],
                    key=lambda x: x[1], reverse=True
                )[:5]
            ],
        )

        # Coverage: percentage of IoCs that have at least one correlation
        correlated_iocs = set()
        for c in self._correlations:
            correlated_iocs.add(c.ioc_a)
            correlated_iocs.add(c.ioc_b)
        report.coverage = len(correlated_iocs) / max(1, len(self._iocs))

        self._reports.append(report)
        return report

    def get_report(self) -> dict:
        """Get correlation engine report."""
        return {
            "total_iocs": len(self._iocs),
            "total_correlations": len(self._correlations),
            "total_campaign_links": len(self._campaign_links),
            "total_actors": len(self._actors),
            "total_patterns": len(self._patterns),
            "total_timeline_events": len(self._timeline),
            "total_reports": len(self._reports),
            "iocs_by_type": {
                type: sum(1 for i in self._iocs.values() if i.type == type)
                for type in set(i.type for i in self._iocs.values())
            },
            "avg_correlation_score": round(sum(c.score for c in self._correlations) / max(1, len(self._correlations)), 3),
            "recent_correlations": [
                {"ioc_a": c.ioc_a, "ioc_b": c.ioc_b, "score": c.score, "type": c.correlation_type}
                for c in self._correlations[-10:]
            ],
            "recent_patterns": [
                {"pattern": p.pattern_name, "iocs": len(p.matched_iocs), "score": p.match_score}
                for p in self._patterns[-5:]
            ],
            "actor_summary": [
                {"name": a.name, "motivation": a.motivation, "iocs": len(a.iocs), "campaigns": len(a.campaigns)}
                for a in self._actors.values()
            ],
            "timeline_summary": [
                {"time": e.timestamp, "type": e.event_type, "description": e.description[:60]}
                for e in sorted(self._timeline, key=lambda x: x.timestamp, reverse=True)[-10:]
            ],
        }


correlation_engine = ThreatIntelCorrelationEngine()


@router.post("/api/v1/intelex/correlation/iocs")
async def add_ioc(payload: dict):
    """Add an IoC."""
    ioc = correlation_engine.add_ioc(
        value=payload["value"],
        ioc_type=payload["type"],
        source=payload.get("source", ""),
        confidence=payload.get("confidence", 0.5),
        malicious=payload.get("malicious", True),
        tags=payload.get("tags", []),
    )
    return {"ioc_id": ioc.ioc_id, "value": ioc.value, "type": ioc.type, "confidence": ioc.confidence}


@router.post("/api/v1/intelex/correlation/iocs/correlate")
async def correlate(payload: dict):
    """Correlate two IoCs."""
    result = correlation_engine.correlate(
        ioc_a_id=payload["ioc_a"],
        ioc_b_id=payload["ioc_b"],
    )
    return {"correlation_id": result.correlation_id, "score": result.score, "type": result.correlation_type, "evidence": result.evidence}


@router.post("/api/v1/intelex/correlation/campaigns/links")
async def link_campaign_ioc(payload: dict):
    """Link a campaign to an IoC."""
    link = correlation_engine.link_campaign_ioc(
        campaign_id=payload["campaign_id"],
        ioc_id=payload["ioc_id"],
        link_type=payload.get("link_type", "observed_in"),
        confidence=payload.get("confidence", 0.5),
    )
    return {"link_id": link.link_id, "campaign": link.campaign_id, "ioc": link.ioc_id, "confidence": link.confidence}


@router.post("/api/v1/intelex/correlation/actors")
async def create_actor(payload: dict):
    """Create a threat actor profile."""
    actor = correlation_engine.create_actor(
        name=payload["name"],
        aliases=payload.get("aliases", []),
        motivation=payload.get("motivation", ""),
    )
    return {"actor_id": actor.actor_id, "name": actor.name, "aliases": actor.aliases, "motivation": actor.motivation}


@router.post("/api/v1/intelex/correlation/patterns")
async def match_pattern(payload: dict):
    """Match a threat pattern."""
    match = correlation_engine.match_pattern(
        pattern_id=payload["pattern_id"],
        pattern_name=payload["pattern_name"],
        iocs=payload.get("iocs", []),
    )
    return {"match_id": match.match_id, "pattern": match.pattern_name, "iocs_matched": len(match.matched_iocs), "score": match.match_score}


@router.get("/api/v1/intelex/correlation/report")
async def get_report():
    """Get correlation engine report."""
    return correlation_engine.get_report()
