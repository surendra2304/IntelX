"""
IntelX/routers/predictive_threat_analyzer.py — IntelX Predictive Threat Intelligence Analyzer.

Analyzes threat intelligence feeds, predicts threat evolution, correlates
attack patterns, and assesses risk across the intelligence landscape using
temporal analysis and graph-based threat modeling.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ThreatIndicator:
    """A threat indicator (IoC)."""
    indicator_id: str
    value: str  # IP, domain, hash, email, etc.
    type: str  # ip, domain, hash, email, url, phishing
    source: str = ""
    confidence: float = 0.5
    first_seen: float = 0.0
    last_seen: float = 0.0
    severity: str = "medium"
    tags: list[str] = field(default_factory=list)
    related_threats: list[str] = field(default_factory=list)
    status: str = "active"


@dataclass
class ThreatActor:
    """A threat actor / hacker group."""
    actor_id: str
    name: str
    alias: str = ""
    motivation: str = ""  # financial, political, espionage, hacktivism, unknown
    sophistication: int = 1  # 1-5
    target_sectors: list[str] = field(default_factory=list)
    known_techniques: list[str] = field(default_factory=list)
    attributed_attacks: int = 0
    first_observed: float = 0.0
    last_active: float = 0.0
    threat_level: str = "medium"


@dataclass
class AttackPattern:
    """An attack pattern."""
    pattern_id: str
    name: str
    technique: str  # MITRE ATT&CK technique
    description: str
    tactics: list[str] = field(default_factory=list)
    complexity: str = "medium"
    success_rate: float = 0.5
    detected_count: int = 0


@dataclass
class ThreatPrediction:
    """A predicted threat."""
    prediction_id: str
    threat_type: str
    description: str
    probability: float
    expected_timeframe: str
    affected_targets: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    risk_score: float = 0.0
    confidence: float = 0.0


@dataclass
class ThreatCorrelation:
    """A correlation between threats."""
    correlation_id: str
    indicators: list[str] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    correlation_score: float = 0.0
    shared_attributes: list[str] = field(default_factory=list)
    time_window_hours: float = 0.0


@dataclass
class ThreatGraph:
    """A graph of threat relationships."""
    graph_id: str
    nodes: list[str] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    cluster_count: int = 0
    most_connected_node: str = ""
    community_detection: list[list[str]] = field(default_factory=list)


class PredictiveThreatAnalyzer:
    """Predictive threat intelligence analyzer."""

    def __init__(self):
        self._indicators: dict[str, ThreatIndicator] = {}
        self._actors: dict[str, ThreatActor] = {}
        self._patterns: dict[str, AttackPattern] = {}
        self._predictions: dict[str, ThreatPrediction] = {}
        self._correlations: dict[str, ThreatCorrelation] = {}
        self._graphs: dict[str, ThreatGraph] = {}

    def add_indicator(
        self,
        value: str,
        indicator_type: str,
        source: str = "",
        confidence: float = 0.5,
        severity: str = "medium",
        tags: list[str] | None = None,
    ) -> ThreatIndicator:
        """Add a threat indicator."""
        indicator = ThreatIndicator(
            indicator_id=hashlib.md5(
                f"indicator:{value}:{indicator_type}:{time.time()}".encode()
            ).hexdigest()[:12],
            value=value,
            type=indicator_type,
            source=source,
            confidence=confidence,
            first_seen=time.time(),
            last_seen=time.time(),
            severity=severity,
            tags=tags or [],
        )
        self._indicators[indicator.indicator_id] = indicator
        return indicator

    def add_threat_actor(
        self,
        name: str,
        alias: str = "",
        motivation: str = "",
        sophistication: int = 1,
        target_sectors: list[str] | None = None,
        known_techniques: list[str] | None = None,
    ) -> ThreatActor:
        """Add a threat actor."""
        actor = ThreatActor(
            actor_id=hashlib.md5(
                f"actor:{name}:{time.time()}".encode()
            ).hexdigest()[:12],
            name=name,
            alias=alias,
            motivation=motivation,
            sophistication=sophistication,
            target_sectors=target_sectors or [],
            known_techniques=known_techniques or [],
            first_observed=time.time(),
            last_active=time.time(),
        )

        # Determine threat level based on sophistication
        if sophistication >= 4:
            actor.threat_level = "critical"
        elif sophistication >= 3:
            actor.threat_level = "high"
        elif sophistication >= 2:
            actor.threat_level = "medium"
        else:
            actor.threat_level = "low"

        self._actors[actor.actor_id] = actor
        return actor

    def predict_threats(self) -> list[ThreatPrediction]:
        """Predict emerging threats."""
        predictions = []

        # Analyze indicators for patterns
        for indicator in self._indicators.values():
            if indicator.confidence > 0.7 and indicator.severity == "high":
                prediction = ThreatPrediction(
                    prediction_id=hashlib.md5(
                        f"prediction:{indicator.indicator_id}:{time.time()}".encode()
                    ).hexdigest()[:12],
                    threat_type="imminent_attack",
                    description=f"High-confidence indicator {indicator.value} suggests imminent attack",
                    probability=indicator.confidence,
                    expected_timeframe="within 24 hours",
                    affected_targets=[s for a in self._actors.values() for s in a.target_sectors],
                    recommended_actions=[
                        "Block indicator at perimeter",
                        "Increase monitoring",
                        "Notify security team",
                        "Review access logs",
                    ],
                    risk_score=indicator.confidence * 100,
                    confidence=indicator.confidence,
                )
                predictions.append(prediction)
                self._predictions[prediction.prediction_id] = prediction

        # Predict based on actor activity
        for actor in self._actors.values():
            if actor.sophistication >= 3 and time.time() - actor.last_active < 86400 * 7:
                prediction = ThreatPrediction(
                    prediction_id=hashlib.md5(
                        f"prediction:actor:{actor.actor_id}:{time.time()}".encode()
                    ).hexdigest()[:12],
                    threat_type="actor_campaign",
                    description=f"Sophisticated actor {actor.name} likely conducting active campaign",
                    probability=0.6 + (actor.sophistication - 3) * 0.1,
                    expected_timeframe="within 1 week",
                    affected_targets=actor.target_sectors,
                    recommended_actions=[
                        f"Monitor for {actor.known_techniques[0] if actor.known_techniques else 'known techniques'}",
                        "Enhance detection rules",
                        "Review privileged access",
                        "Conduct threat hunting",
                    ],
                    risk_score=actor.sophistication * 20,
                    confidence=0.7,
                )
                predictions.append(prediction)
                self._predictions[prediction.prediction_id] = prediction

        return predictions

    def correlate_threats(self) -> list[ThreatCorrelation]:
        """Correlate related threats."""
        correlations = []

        # Group indicators by tags
        tag_groups: dict[str, list[str]] = {}
        for indicator in self._indicators.values():
            for tag in indicator.tags:
                if tag not in tag_groups:
                    tag_groups[tag] = []
                tag_groups[tag].append(indicator.indicator_id)

        # Create correlations for shared tags
        for tag, indicator_ids in tag_groups.items():
            if len(indicator_ids) > 1:
                correlation = ThreatCorrelation(
                    correlation_id=hashlib.md5(
                        f"correlation:{tag}:{time.time()}".encode()
                    ).hexdigest()[:12],
                    indicators=indicator_ids,
                    correlation_score=min(1.0, len(indicator_ids) * 0.2),
                    shared_attributes=[f"Shared tag: {tag}"],
                    time_window_hours=86400,
                )
                correlations.append(correlation)
                self._correlations[correlation.correlation_id] = correlation

        return correlations

    def build_threat_graph(self) -> ThreatGraph:
        """Build a threat relationship graph."""
        nodes = list(self._indicators.keys()) + list(self._actors.keys())
        edges = []

        # Connect indicators to actors via shared attributes
        for indicator in self._indicators.values():
            for actor in self._actors.values():
                if any(t in actor.known_techniques for t in indicator.tags):
                    edges.append({
                        "source": indicator.indicator_id,
                        "target": actor.actor_id,
                        "relationship": "attributed",
                    })

        # Find most connected node
        node_counts: dict[str, int] = {}
        for edge in edges:
            node_counts[edge["source"]] = node_counts.get(edge["source"], 0) + 1
            node_counts[edge["target"]] = node_counts.get(edge["target"], 0) + 1

        most_connected = max(node_counts, key=node_counts.get, default="")

        graph = ThreatGraph(
            graph_id=hashlib.md5(
                f"graph:{time.time()}".encode()
            ).hexdigest()[:12],
            nodes=nodes,
            edges=edges,
            cluster_count=len(set(e["source"] for e in edges)),
            most_connected_node=most_connected,
            community_detection=[nodes[:3], nodes[3:6] if len(nodes) > 6 else nodes[3:]],
        )

        self._graphs[graph.graph_id] = graph
        return graph

    def assess_risk(self) -> dict:
        """Assess overall threat landscape risk."""
        total_indicators = len(self._indicators)
        high_confidence = sum(1 for i in self._indicators.values() if i.confidence > 0.7)
        critical_actors = sum(1 for a in self._actors.values() if a.threat_level == "critical")
        high_actors = sum(1 for a in self._actors.values() if a.threat_level == "high")

        risk_score = (
            high_confidence * 10 +
            critical_actors * 25 +
            high_actors * 15 +
            total_indicators * 2
        )

        if risk_score > 70:
            overall_risk = "critical"
        elif risk_score > 50:
            overall_risk = "high"
        elif risk_score > 30:
            overall_risk = "medium"
        else:
            overall_risk = "low"

        return {
            "risk_score": risk_score,
            "overall_risk": overall_risk,
            "total_indicators": total_indicators,
            "high_confidence_indicators": high_confidence,
            "critical_actors": critical_actors,
            "high_actors": high_actors,
            "total_actors": len(self._actors),
            "correlations": len(self._correlations),
        }

    def get_report(self) -> dict:
        """Get threat analyzer report."""
        return {
            "total_indicators": len(self._indicators),
            "total_actors": len(self._actors),
            "total_patterns": len(self._patterns),
            "total_predictions": len(self._predictions),
            "total_correlations": len(self._correlations),
            "indicator_types": {
                t: sum(1 for i in self._indicators.values() if i.type == t)
                for t in set(i.type for i in self._indicators.values())
            },
            "actor_motivations": {
                m: sum(1 for a in self._actors.values() if a.motivation == m)
                for m in set(a.motivation for a in self._actors.values())
            },
            "recent_predictions": [
                {
                    "threat_type": p.threat_type,
                    "description": p.description[:100],
                    "probability": p.probability,
                    "risk_score": p.risk_score,
                }
                for p in list(self._predictions.values())[-5:]
            ],
        }


# Module-level singleton
threat_analyzer = PredictiveThreatAnalyzer()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/intelex/threat/indicators")
async def add_indicator(payload: dict):
    """Add a threat indicator."""
    indicator = threat_analyzer.add_indicator(
        value=payload["value"],
        indicator_type=payload["type"],
        source=payload.get("source", ""),
        confidence=payload.get("confidence", 0.5),
        severity=payload.get("severity", "medium"),
        tags=payload.get("tags", []),
    )
    return {"indicator_id": indicator.indicator_id, "value": indicator.value, "type": indicator.type}


@router.post("/api/v1/intelex/threat/actors")
async def add_threat_actor(payload: dict):
    """Add a threat actor."""
    actor = threat_analyzer.add_threat_actor(
        name=payload["name"],
        alias=payload.get("alias", ""),
        motivation=payload.get("motivation", ""),
        sophistication=payload.get("sophistication", 1),
        target_sectors=payload.get("target_sectors", []),
        known_techniques=payload.get("known_techniques", []),
    )
    return {"actor_id": actor.actor_id, "name": actor.name, "threat_level": actor.threat_level}


@router.get("/api/v1/intelex/threat/predict")
async def predict_threats():
    """Predict emerging threats."""
    predictions = threat_analyzer.predict_threats()
    return [p.__dict__ for p in predictions]


@router.get("/api/v1/intelex/threat/correlate")
async def correlate_threats():
    """Correlate related threats."""
    correlations = threat_analyzer.correlate_threats()
    return [c.__dict__ for c in correlations]


@router.post("/api/v1/intelex/threat/graph")
async def build_threat_graph():
    """Build threat relationship graph."""
    graph = threat_analyzer.build_threat_graph()
    return {
        "graph_id": graph.graph_id,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "cluster_count": graph.cluster_count,
        "most_connected_node": graph.most_connected_node,
    }


@router.get("/api/v1/intelex/threat/risk")
async def assess_risk():
    """Assess overall threat landscape risk."""
    return threat_analyzer.assess_risk()


@router.get("/api/v1/intelex/threat/report")
async def get_report():
    """Get threat analyzer report."""
    return threat_analyzer.get_report()
