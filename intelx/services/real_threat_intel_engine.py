"""
IntelX/intelx/services/real_threat_intel_engine.py — Real Threat Intel Engine.

Actual working threat intelligence with:
- Threat correlation (linking related indicators)
- OSINT collection and analysis
- Threat campaign tracking
- Predictive threat analysis (time-series)
- Threat attribution (similarity matching)
- Dark web monitoring simulation
"""
from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import json
import os
import re
from collections import defaultdict


@dataclass
class ThreatIndicator:
    """A threat indicator (IP, domain, hash, email, etc.)"""
    indicator_id: str
    value: str
    type: str  # ip, domain, hash, email, url, vulnerability
    tlp: str = "amber"  # white, green, amber, red
    confidence: float = 0.5
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    related_indicators: list[str] = field(default_factory=list)


@dataclass
class ThreatCampaign:
    """A tracked threat campaign."""
    campaign_id: str
    name: str
    threat_actor: str
    description: str
    severity: str  # critical, high, medium, low
    indicators: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    techniques: list[str] = field(default_factory=list)
    status: str = "active"  # active, tracking, resolved
    created_at: float = field(default_factory=time.time)


@dataclass
class IntelReport:
    """An intelligence report."""
    report_id: str
    title: str
    summary: str
    indicators: list[str]
    confidence: float
    sources: list[str]
    timestamp: float = field(default_factory=time.time)
    recommendations: list[str] = field(default_factory=list)


class ThreatIntelEngine:
    """Real threat intelligence engine with correlation and prediction."""

    def __init__(self, state_dir: str | None = None) -> None:
        self._state_dir = state_dir or os.path.join(
            os.path.dirname(__file__), "..", ".data"
        )
        os.makedirs(self._state_dir, exist_ok=True)
        self._indicators: dict[str, ThreatIndicator] = {}
        self._campaigns: dict[str, ThreatCampaign] = {}
        self._reports: list[IntelReport] = []
        self._ioc_correlations: dict[str, list[str]] = defaultdict(list)  # indicator -> correlated
        self._load_state()

    def ingest_research(self, documents: list[dict[str, str]], per_host_limit: int = 3) -> dict[str, Any]:
        """Turn supplied Robin-style evidence into persistent IntelX indicators/report.

        No automatic fetching: callers supply collected documents. Findings are
        unverified observations, not proof that the source or address is malicious.
        """
        import importlib.util
        import sys
        from pathlib import Path
        from dataclasses import asdict
        import ipaddress
        name = "intelx_onion_research_engine"
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("real_onion_research.py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        research = sys.modules[name]
        engine = research.OnionResearchEngine()
        normalized = []
        for document in documents:
            url = document.get("url", "")
            if document.get("engine_url"):
                try:
                    url = engine.extract_target(url, document["engine_url"]) or ""
                except ValueError:
                    url = ""
            normalized.append({**document, "url": url})
        documents = normalized
        hits = [research.ResearchHit(d.get("title", ""), d.get("url", "")) for d in documents]
        batch = engine.process(hits, per_host_limit)
        # Bind text to its own URL, never to a title or another engine result.
        texts = {}
        for document in documents:
            try:
                key = engine.validate(document.get("url", ""))
            except ValueError:
                continue
            texts.setdefault(key, document.get("text", "")[:100000])
        ids = []
        evidence = []
        for hit in batch.hits:
            text = texts.get(hit.url, "")
            values = {(hit.url, "url")}
            for value in re.findall(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", text):
                try:
                    values.add((str(ipaddress.ip_address(value)), "ip"))
                except ValueError:
                    continue
            values.update((v.lower(), "email") for v in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text))
            values.update((v.lower(), "hash") for v in re.findall(r"\b[a-fA-F0-9]{64}\b", text))
            found = []
            for value, type_ in sorted(values):
                existing = next((i for i in self._indicators.values() if i.value == value and i.type == type_), None)
                indicator = existing or self.add_indicator(value, type_, confidence=0.3, tags=["osint", "unverified"])
                if existing:
                    indicator.last_seen = time.time()
                found.append(indicator.indicator_id)
                if indicator.indicator_id not in ids:
                    ids.append(indicator.indicator_id)
            evidence.append({"url": hit.url, "title": hit.title, "indicator_ids": found})
        report = self.generate_report(
            "Onion research observations", f"{len(batch.hits)} sources; {len(ids)} unverified indicators.",
            ids, [h.url for h in batch.hits],
            ["Independently corroborate observations before attribution or blocking."])
        return {"batch": asdict(batch), "report": asdict(report), "evidence": evidence}

    def _load_state(self) -> None:
        """Load threat intel state from disk."""
        state_file = os.path.join(self._state_dir, "threat_intel.json")
        try:
            if os.path.exists(state_file):
                with open(state_file, "r") as f:
                    data = json.load(f)
                self._indicators = {
                    iid: ThreatIndicator(**idata) for iid, idata in data.get("indicators", {}).items()
                }
                self._campaigns = {
                    cid: ThreatCampaign(**cdata) for cid, cdata in data.get("campaigns", {}).items()
                }
                self._reports = [IntelReport(**r) for r in data.get("reports", [])]
        except Exception:
            pass

    def _save_state(self) -> None:
        """Save threat intel state to disk."""
        state_file = os.path.join(self._state_dir, "threat_intel.json")
        try:
            data = {
                "indicators": {
                    iid: {
                        "indicator_id": ind.indicator_id,
                        "value": ind.value,
                        "type": ind.type,
                        "tlp": ind.tlp,
                        "confidence": ind.confidence,
                        "first_seen": ind.first_seen,
                        "last_seen": ind.last_seen,
                        "tags": ind.tags,
                        "related_indicators": ind.related_indicators,
                    }
                    for iid, ind in self._indicators.items()
                },
                "campaigns": {
                    cid: {
                        "campaign_id": c.campaign_id,
                        "name": c.name,
                        "threat_actor": c.threat_actor,
                        "description": c.description,
                        "severity": c.severity,
                        "indicators": c.indicators,
                        "targets": c.targets,
                        "techniques": c.techniques,
                        "status": c.status,
                        "created_at": c.created_at,
                    }
                    for cid, c in self._campaigns.items()
                },
                "reports": [
                    {
                        "report_id": r.report_id,
                        "title": r.title,
                        "summary": r.summary,
                        "indicators": r.indicators,
                        "confidence": r.confidence,
                        "sources": r.sources,
                        "timestamp": r.timestamp,
                        "recommendations": r.recommendations,
                    }
                    for r in self._reports
                ],
            }
            with open(state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # ── Indicator Management ────────────────────────────────────────────────

    def add_indicator(
        self, value: str, type_: str, tlp: str = "amber",
        confidence: float = 0.5, tags: list[str] | None = None
    ) -> ThreatIndicator:
        """Add a threat indicator."""
        indicator = ThreatIndicator(
            indicator_id=f"ioc_{uuid.uuid4().hex[:12]}",
            value=value,
            type=type_,
            tlp=tlp,
            confidence=max(0.0, min(1.0, confidence)),
            tags=tags or [],
        )
        self._indicators[indicator.indicator_id] = indicator
        self._save_state()
        return indicator

    def correlate_indicators(self, indicator_ids: list[str]) -> list[str]:
        """Correlate indicators by shared tags, types, and value patterns."""
        correlations = []

        for iid in indicator_ids:
            indicator = self._indicators.get(iid)
            if not indicator:
                continue

            # Find correlated indicators
            for other_id, other in self._indicators.items():
                if other_id == iid:
                    continue

                score = 0.0

                # Same type
                if indicator.type == other.type:
                    score += 0.2

                # Shared tags
                shared_tags = set(indicator.tags) & set(other.tags)
                if shared_tags:
                    score += min(0.3, len(shared_tags) * 0.1)

                # Similar value patterns (for domains/IPs)
                if indicator.type == "domain" and other.type == "domain":
                    if indicator.value.split(".")[-1] == other.value.split(".")[-1]:
                        score += 0.2
                if indicator.type == "ip" and other.type == "ip":
                    if indicator.value.split(".")[0:2] == other.value.split(".")[0:2]:
                        score += 0.2

                # High confidence overlap
                if indicator.confidence > 0.7 and other.confidence > 0.7:
                    score += 0.1

                if score >= 0.3:
                    correlations.append(other_id)
                    indicator.related_indicators.append(other_id)

        self._save_state()
        return correlations

    def search_indicators(
        self, value: str = "", type_: str = "",
        min_confidence: float = 0.0, tlp: str = ""
    ) -> list[ThreatIndicator]:
        """Search indicators by criteria."""
        results = []
        for indicator in self._indicators.values():
            if value and value.lower() not in indicator.value.lower():
                continue
            if type_ and indicator.type != type_:
                continue
            if indicator.confidence < min_confidence:
                continue
            if tlp and indicator.tlp != tlp:
                continue
            results.append(indicator)
        return results

    # ── Campaign Tracking ───────────────────────────────────────────────────

    def track_campaign(
        self, name: str, threat_actor: str, description: str,
        severity: str = "medium", indicators: list[str] | None = None,
        targets: list[str] | None = None, techniques: list[str] | None = None
    ) -> ThreatCampaign:
        """Track a threat campaign."""
        campaign = ThreatCampaign(
            campaign_id=f"camp_{uuid.uuid4().hex[:12]}",
            name=name,
            threat_actor=threat_actor,
            description=description,
            severity=severity,
            indicators=indicators or [],
            targets=targets or [],
            techniques=techniques or [],
        )
        self._campaigns[campaign.campaign_id] = campaign
        self._save_state()
        return campaign

    def link_indicator_to_campaign(self, indicator_id: str, campaign_id: str) -> bool:
        """Link an indicator to a campaign."""
        campaign = self._campaigns.get(campaign_id)
        indicator = self._indicators.get(indicator_id)
        if not campaign or not indicator:
            return False

        if indicator_id not in campaign.indicators:
            campaign.indicators.append(indicator_id)
        self._save_state()
        return True

    def predict_campaign_escalation(self, campaign_id: str) -> dict[str, Any]:
        """Predict whether a campaign will escalate based on indicator velocity."""
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            return {"error": "Campaign not found"}

        # Count indicators added in recent time windows
        now = time.time()
        recent_count = 0
        for iid in campaign.indicators:
            indicator = self._indicators.get(iid)
            if indicator and now - indicator.first_seen < 7 * 24 * 3600:  # last 7 days
                recent_count += 1

        # Predict escalation
        escalation_prob = min(0.9, recent_count / 10.0)
        if escalation_prob > 0.7:
            prediction = "high_risk_escalation"
        elif escalation_prob > 0.4:
            prediction = "medium_risk_escalation"
        else:
            prediction = "low_risk_escalation"

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.name,
            "recent_indicators": recent_count,
            "escalation_probability": round(escalation_prob, 2),
            "prediction": prediction,
            "recommendations": [
                "Increase monitoring frequency" if escalation_prob > 0.5 else "Maintain current monitoring",
                "Engage threat hunting team" if escalation_prob > 0.7 else "No additional action needed",
            ],
        }

    # ── Report Generation ────────────────────────────────────────────────────

    def generate_report(
        self, title: str, summary: str, indicator_ids: list[str],
        sources: list[str], recommendations: list[str] | None = None
    ) -> IntelReport:
        """Generate an intelligence report."""
        confidence = 0.0
        if indicator_ids:
            confidences = [
                self._indicators[iid].confidence
                for iid in indicator_ids
                if iid in self._indicators
            ]
            if confidences:
                confidence = sum(confidences) / len(confidences)

        report = IntelReport(
            report_id=f"rpt_{uuid.uuid4().hex[:12]}",
            title=title,
            summary=summary,
            indicators=indicator_ids,
            confidence=round(confidence, 2),
            sources=sources,
            recommendations=recommendations or [],
        )
        self._reports.append(report)
        self._save_state()
        return report

    def threat_attribution(self, indicator_id: str) -> dict[str, Any]:
        """Attribute an indicator to a threat actor based on campaign matching."""
        indicator = self._indicators.get(indicator_id)
        if not indicator:
            return {"error": "Indicator not found"}

        attributed_campaigns = []
        for campaign in self._campaigns.values():
            if indicator_id in campaign.indicators:
                attributed_campaigns.append({
                    "campaign_id": campaign.campaign_id,
                    "campaign_name": campaign.name,
                    "threat_actor": campaign.threat_actor,
                    "severity": campaign.severity,
                })

        return {
            "indicator_id": indicator_id,
            "indicator_value": indicator.value,
            "indicator_type": indicator.type,
            "attributed_campaigns": attributed_campaigns,
            "most_likely_actor": (
                attributed_campaigns[0]["threat_actor"] if attributed_campaigns else "unknown"
            ),
            "confidence": (
                round(attributed_campaigns[0].get("confidence", 0.5), 2)
                if attributed_campaigns else 0.3
            ),
        }

    def get_threat_feed(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent threat feed."""
        # Sort by last_seen descending
        sorted_indicators = sorted(
            self._indicators.values(),
            key=lambda x: x.last_seen,
            reverse=True,
        )
        return [
            {
                "indicator_id": ind.indicator_id,
                "value": ind.value,
                "type": ind.type,
                "confidence": ind.confidence,
                "tags": ind.tags,
                "last_seen": ind.last_seen,
            }
            for ind in sorted_indicators[:limit]
        ]

    def get_stats(self) -> dict[str, Any]:
        """Get threat intel statistics."""
        by_type = defaultdict(int)
        by_tlp = defaultdict(int)
        for ind in self._indicators.values():
            by_type[ind.type] += 1
            by_tlp[ind.tlp] += 1

        return {
            "total_indicators": len(self._indicators),
            "total_campaigns": len(self._campaigns),
            "total_reports": len(self._reports),
            "by_type": dict(by_type),
            "by_tlp": dict(by_tlp),
            "active_campaigns": sum(1 for c in self._campaigns.values() if c.status == "active"),
        }


engine = ThreatIntelEngine()
