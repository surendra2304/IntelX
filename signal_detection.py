"""
IntelX/signal_detection.py — IntelX Intelligence Signal Detection Engine.

Extends IntelX's capabilities with:
1. Multi-Source Signal Monitoring: monitor signals from various sources
2. Signal Fusion: combine signals from multiple sources
3. Anomaly Detection: detect anomalies in signal streams
4. Signal Classification: classify signals by type and priority
5. Threat Correlation: correlate signals to identify threats
6. Predictive Signal Analysis: predict future signal patterns
7. Signal Alerting: generate alerts from important signals
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class Signal:
    """An intelligence signal."""
    signal_id: str
    source: str  # osint, social, news, financial, technical
    content: str
    timestamp: float
    confidence: float = 0.5
    severity: str = "low"  # low, medium, high, critical
    category: str = "general"
    entities: list[str] = field(default_factory=list)
    related_signals: list[str] = field(default_factory=list)


@dataclass
class SignalFusionResult:
    """Result of fusing multiple signals."""
    fused_id: str
    signals_fused: list[str]
    fuse_confidence: float
    fuse_severity: str
    assessment: str
    recommended_action: str
    entities: list[str]


@dataclass
class Anomaly:
    """Detected anomaly."""
    anomaly_id: str
    signal_id: str
    anomaly_type: str  # statistical, pattern, temporal, volume
    severity: str
    description: str
    deviation_score: float
    recommended_response: str


@dataclass
class ThreatAssessment:
    """Threat assessment from correlated signals."""
    threat_id: str
    threat_type: str  # cyber, physical, financial, reputational
    severity: str
    confidence: float
    indicators: list[str]
    affected_entities: list[str]
    recommended_actions: list[str]
    assessment: str


@dataclass
class SignalPrediction:
    """Predicted future signal pattern."""
    topic: str
    predicted_signals: int
    confidence: float
    timeframe: str
    trend: str  # increasing, decreasing, stable
    risk_level: str


@dataclass
class Alert:
    """Generated alert from signals."""
    alert_id: str
    alert_type: str
    severity: str
    message: str
    related_signals: list[str]
    recipients: list[str]
    timestamp: float


class SignalDetector:
    """Intelligence signal detection engine."""

    def __init__(self):
        self._signals: list[Signal] = []
        self._fused: dict[str, SignalFusionResult] = {}
        self._anomalies: list[Anomaly] = []
        self._threats: list[ThreatAssessment] = {}
        self._alerts: list[Alert] = []

    # ── Multi-Source Signal Monitoring ───────────────────────────────────

    def ingest_signal(
        self,
        source: str,
        content: str,
        confidence: float = 0.5,
        category: str = "general",
        entities: list[str] | None = None,
    ) -> Signal:
        """Ingest a signal from a source."""
        signal = Signal(
            signal_id=hashlib.md5(
                f"signal:{source}:{content}:{time.time()}".encode()
            ).hexdigest()[:12],
            source=source,
            content=content,
            timestamp=time.time(),
            confidence=confidence,
            severity=self._classify_severity(content, confidence),
            category=category,
            entities=entities or [],
        )

        self._signals.append(signal)

        # Check for anomalies
        anomaly = self._detect_anomaly(signal)
        if anomaly:
            self._anomalies.append(anomaly)

        return signal

    def _classify_severity(self, content: str, confidence: float) -> str:
        severity_words = {
            "critical": ["attack", "breach", "exploit", "vulnerability", "urgent"],
            "high": ["warning", "threat", "risk", "alert", "critical"],
            "medium": ["concern", "issue", "unusual", "anomaly", "investigate"],
        }

        content_lower = content.lower()
        for level, words in severity_words.items():
            if any(w in content_lower for w in words):
                return level

        if confidence > 0.8:
            return "medium"
        return "low"

    # ── Signal Fusion ─────────────────────────────────────────────────────

    def fuse_signals(
        self,
        signal_ids: list[str],
    ) -> SignalFusionResult | None:
        """Fuse multiple signals into a single assessment."""
        signals = [
            s for s in self._signals
            if s.signal_id in signal_ids
        ]

        if len(signals) < 2:
            return None

        # Calculate fused confidence
        avg_confidence = sum(s.confidence for s in signals) / len(signals)

        # Determine fused severity
        severities = [s.severity for s in signals]
        if "critical" in severities:
            fused_severity = "critical"
        elif "high" in severities:
            fused_severity = "high"
        elif "medium" in severities:
            fused_severity = "medium"
        else:
            fused_severity = "low"

        # Assessment
        assessment = self._generate_assessment(signals)

        # Recommended action
        if fused_severity in ("critical", "high"):
            action = "Immediate investigation and response required"
        elif fused_severity == "medium":
            action = "Monitor closely and investigate within 24 hours"
        else:
            action = "Continue monitoring"

        # Entities
        all_entities = set()
        for s in signals:
            all_entities.update(s.entities)

        fused_id = hashlib.md5(f"fused:{time.time()}".encode()).hexdigest()[:12]

        result = SignalFusionResult(
            fused_id=fused_id,
            signals_fused=signal_ids,
            fuse_confidence=avg_confidence,
            fuse_severity=fused_severity,
            assessment=assessment,
            recommended_action=action,
            entities=list(all_entities),
        )

        self._fused[fused_id] = result
        return result

    def _generate_assessment(self, signals: list[Signal]) -> str:
        """Generate assessment from fused signals."""
        sources = set(s.source for s in signals)
        categories = set(s.category for s in signals)

        assessment = (
            f"Fused {len(signals)} signals from {len(sources)} sources "
            f"({', '.join(sources)}). "
            f"Categories: {', '.join(categories)}. "
            f"Cross-source validation increases reliability."
        )

        return assessment

    # ── Anomaly Detection ─────────────────────────────────────────────────

    def _detect_anomaly(self, signal: Signal) -> Anomaly | None:
        """Detect anomalies in incoming signals."""
        # Check for volume anomaly
        recent_signals = [
            s for s in self._signals
            if s.timestamp > time.time() - 60  # last minute
        ]

        if len(recent_signals) > 20:
            return Anomaly(
                anomaly_id=hashlib.md5(
                    f"anomaly:volume:{time.time()}".encode()
                ).hexdigest()[:12],
                signal_id=signal.signal_id,
                anomaly_type="volume",
                severity="medium",
                description=f"Signal volume spike: {len(recent_signals)} signals in 1 minute",
                deviation_score=len(recent_signals) / 20,
                recommended_response="Increase monitoring, check for coordinated activity",
            )

        # Check for severity anomaly
        if signal.severity == "critical" and signal.confidence > 0.7:
            return Anomaly(
                anomaly_id=hashlib.md5(
                    f"anomaly:severity:{time.time()}".encode()
                ).hexdigest()[:12],
                signal_id=signal.signal_id,
                anomaly_type="severity",
                severity="critical",
                description=f"High-severity signal detected: {signal.content[:100]}",
                deviation_score=1.0,
                recommended_response="Immediate escalation and response",
            )

        return None

    def get_anomalies(self) -> list[Anomaly]:
        return sorted(self._anomalies, key=lambda a: -a.deviation_score)

    # ── Signal Classification ────────────────────────────────────────────

    def classify_signals(self) -> dict[str, list[Signal]]:
        """Classify all signals by type and severity."""
        classified = {}

        for signal in self._signals:
            key = f"{signal.severity}_{signal.category}"
            if key not in classified:
                classified[key] = []
            classified[key].append(signal)

        return classified

    # ── Threat Correlation ───────────────────────────────────────────────

    def correlate_threats(
        self,
        signal_ids: list[str],
    ) -> ThreatAssessment | None:
        """Correlate signals to identify threats."""
        signals = [
            s for s in self._signals
            if s.signal_id in signal_ids
        ]

        if len(signals) < 2:
            return None

        # Determine threat type
        categories = set(s.category for s in signals)

        if any("cyber" in c.lower() for c in categories):
            threat_type = "cyber"
        elif any("financial" in c.lower() for c in categories):
            threat_type = "financial"
        elif any("reputation" in c.lower() for c in categories):
            threat_type = "reputational"
        else:
            threat_type = "general"

        # Severity
        if any(s.severity == "critical" for s in signals):
            severity = "critical"
        elif any(s.severity == "high" for s in signals):
            severity = "high"
        else:
            severity = "medium"

        # Confidence
        confidence = sum(s.confidence for s in signals) / len(signals)

        # Indicators
        indicators = [s.content[:100] for s in signals]

        # Affected entities
        entities = set()
        for s in signals:
            entities.update(s.entities)

        # Recommended actions
        actions = []
        if severity in ("critical", "high"):
            actions = ["Activate incident response", "Notify stakeholders", "Collect additional intelligence"]
        else:
            actions = ["Monitor situation", "Gather more information", "Prepare response plan"]

        threat_id = hashlib.md5(f"threat:{time.time()}".encode()).hexdigest()[:12]

        threat = ThreatAssessment(
            threat_id=threat_id,
            threat_type=threat_type,
            severity=severity,
            confidence=confidence,
            indicators=indicators,
            affected_entities=list(entities),
            recommended_actions=actions,
            assessment=self._generate_threat_assessment(signals, threat_type),
        )

        self._threats[threat_id] = threat
        return threat

    def _generate_threat_assessment(
        self,
        signals: list[Signal],
        threat_type: str,
    ) -> str:
        assessment = (
            f"Correlated {len(signals)} signals indicating potential {threat_type} threat. "
            f"Sources: {', '.join(set(s.source for s in signals))}. "
            f"Confidence: {sum(s.confidence for s in signals) / len(signals):.2f}. "
        )

        if threat_type == "cyber":
            assessment += "Recommended: verify indicators, check for vulnerabilities, implement mitigations."
        elif threat_type == "financial":
            assessment += "Recommended: verify market data, check for market manipulation patterns."
        else:
            assessment += "Recommended: gather additional context, monitor for escalation."

        return assessment

    def get_threat_assessments(self) -> list[ThreatAssessment]:
        return sorted(
            self._threats.values(),
            key=lambda t: -ord(t.severity[0]) if t.severity else 0
        )

    # ── Predictive Signal Analysis ────────────────────────────────────────

    def predict_signal_patterns(
        self,
        topic: str,
        historical_signals: list[Signal],
    ) -> SignalPrediction:
        """Predict future signal patterns."""
        # Count historical signals for this topic
        topic_signals = [
            s for s in historical_signals
            if topic.lower() in s.content.lower()
        ]

        # Trend analysis
        if len(topic_signals) >= 5:
            # Compare recent vs older
            midpoint = len(topic_signals) // 2
            recent = topic_signals[midpoint:]
            older = topic_signals[:midpoint]

            if len(recent) > len(older) * 1.5:
                trend = "increasing"
            elif len(recent) < len(older) * 0.7:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "unknown"

        # Predict future signals
        base_rate = len(topic_signals) / max(1, max(s.timestamp for s in historical_signals) - min(s.timestamp for s in historical_signals))
        predicted = int(base_rate * 86400 * 7)  # next week

        # Risk level
        if trend == "increasing" and len(topic_signals) > 10:
            risk_level = "high"
        elif trend == "increasing":
            risk_level = "medium"
        else:
            risk_level = "low"

        return SignalPrediction(
            topic=topic,
            predicted_signals=predicted,
            confidence=min(0.8, 0.5 + len(topic_signals) * 0.02),
            timeframe="7 days",
            trend=trend,
            risk_level=risk_level,
        )

    # ── Signal Alerting ───────────────────────────────────────────────────

    def generate_alerts(self) -> list[Alert]:
        """Generate alerts from important signals and threats."""
        self._alerts = []

        # Alerts from critical/high severity signals
        for signal in self._signals:
            if signal.severity in ("critical", "high"):
                self._alerts.append(Alert(
                    alert_id=hashlib.md5(
                        f"alert:signal:{signal.signal_id}:{time.time()}".encode()
                    ).hexdigest()[:12],
                    alert_type="signal_alert",
                    severity=signal.severity,
                    message=signal.content[:200],
                    related_signals=[signal.signal_id],
                    recipients=["security_team", "intelx_command"],
                    timestamp=time.time(),
                ))

        # Alerts from fused assessments
        for fused in self._fused.values():
            if fused.fuse_severity in ("critical", "high"):
                self._alerts.append(Alert(
                    alert_id=hashlib.md5(
                        f"alert:fused:{fused.fused_id}:{time.time()}".encode()
                    ).hexdigest()[:12],
                    alert_type="fusion_alert",
                    severity=fused.fuse_severity,
                    message=fused.assessment,
                    related_signals=fused.signals_fused,
                    recipients=["security_team", "intelx_command", "friday"],
                    timestamp=time.time(),
                ))

        # Alerts from threats
        for threat in self._threats.values():
            if threat.severity in ("critical", "high"):
                self._alerts.append(Alert(
                    alert_id=hashlib.md5(
                        f"alert:threat:{threat.threat_id}:{time.time()}".encode()
                    ).hexdigest()[:12],
                    alert_type="threat_alert",
                    severity=threat.severity,
                    message=threat.assessment,
                    related_signals=threat.indicators,
                    recipients=["security_team", "intelx_command", "friday", "sentinel"],
                    timestamp=time.time(),
                ))

        return self._alerts

    def get_alerts(self) -> list[Alert]:
        return sorted(self._alerts, key=lambda a: -ord(a.severity[0]) if a.severity else 0)

    # ── Reporting ────────────────────────────────────────────────────────

    def get_signal_report(self) -> dict:
        """Get comprehensive signal report."""
        return {
            "total_signals": len(self._signals),
            "total_fused": len(self._fused),
            "total_anomalies": len(self._anomalies),
            "total_threats": len(self._threats),
            "total_alerts": len(self._alerts),
            "signals_by_severity": {
                sev: sum(1 for s in self._signals if s.severity == sev)
                for sev in ("critical", "high", "medium", "low")
            },
            "signals_by_source": {
                src: sum(1 for s in self._signals if s.source == src)
                for src in set(s.source for s in self._signals)
            },
        }


# ── API Routes ──────────────────────────────────────────────────────────────

signal_detector = SignalDetector()


@router.post("/api/v1/intel/signals/ingest")
async def ingest_signal(payload: dict):
    """Ingest a signal."""
    signal = signal_detector.ingest_signal(
        source=payload["source"],
        content=payload["content"],
        confidence=payload.get("confidence", 0.5),
        category=payload.get("category", "general"),
        entities=payload.get("entities", []),
    )
    return signal.__dict__


@router.post("/api/v1/intel/signals/fuse")
async def fuse_signals(payload: dict):
    """Fuse multiple signals."""
    result = signal_detector.fuse_signals(payload["signal_ids"])
    if not result:
        raise HTTPException(400, "Need at least 2 signals to fuse")
    return result.__dict__


@router.get("/api/v1/intel/signals/anomalies")
async def get_anomalies():
    """Get anomalies."""
    return [a.__dict__ for a in signal_detector.get_anomalies()]


@router.get("/api/v1/intel/signals/classified")
async def classify_signals():
    """Classify signals."""
    classified = signal_detector.classify_signals()
    return {
        key: [s.__dict__ for s in signals]
        for key, signals in classified.items()
    }


@router.post("/api/v1/intel/signals/correlate")
async def correlate_threats(payload: dict):
    """Correlate signals for threats."""
    threat = signal_detector.correlate_threats(payload["signal_ids"])
    if not threat:
        raise HTTPException(400, "Need at least 2 signals to correlate")
    return threat.__dict__


@router.get("/api/v1/intel/signals/threats")
async def get_threat_assessments():
    """Get threat assessments."""
    return [t.__dict__ for t in signal_detector.get_threat_assessments()]


@router.post("/api/v1/intel/signals/predict")
async def predict_signal_patterns(payload: dict):
    """Predict signal patterns."""
    prediction = signal_detector.predict_signal_patterns(
        topic=payload["topic"],
        historical_signals=payload.get("historical_signals", []),
    )
    return prediction.__dict__


@router.get("/api/v1/intel/signals/alerts")
async def get_alerts():
    """Get alerts."""
    alerts = signal_detector.generate_alerts()
    return [a.__dict__ for a in alerts]


@router.get("/api/v1/intel/signals/report")
async def get_signal_report():
    """Get signal report."""
    return signal_detector.get_signal_report()
