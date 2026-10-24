"""
IntelX/routers/dynamic_osint_collector.py — IntelX Dynamic OSINT Collection Framework.

Dynamically orchestrates OSINT data collection across multiple sources:
web scraping, social media, dark web, DNS, certificate transparency, WHOIS,
and public data APIs. Includes source reliability scoring and data fusion.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class OSINTSource:
    """An OSINT collection source."""
    source_id: str
    name: str
    source_type: str  # web, social, dark_web, dns, ct_log, whois, api, metadata
    url: str = ""
    reliability: float = 0.5
    last_collection: float = 0.0
    collection_count: int = 0
    rate_limit: float = 1.0  # requests per second
    auth_required: bool = False
    status: str = "available"
    supported_data: list[str] = field(default_factory=list)


@dataclass
class CollectionTask:
    """A collection task."""
    task_id: str
    target: str
    target_type: str  # ip, domain, email, hash, url, phone
    sources: list[str] = field(default_factory=list)
    status: str = "pending"
    started_at: float = 0.0
    completed_at: float = 0.0
    results_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class OSINTFinding:
    """A finding from OSINT collection."""
    finding_id: str
    task_id: str
    source: str
    finding_type: str  # username, email, ip, domain, hash, phone, profile, document
    value: str
    context: str = ""
    timestamp: float = 0.0
    confidence: float = 0.5
    reliability: float = 0.5
    metadata: dict = field(default_factory=dict)
    related_to_target: bool = True


@dataclass
class SourceReliability:
    """Reliability assessment for a source."""
    source_id: str
    name: str
    overall_score: float
    accuracy: float
    freshness: float
    completeness: float
    error_rate: float
    recommendation: str = ""


@dataclass
class DataFusionResult:
    """Result of fusing OSINT data from multiple sources."""
    fusion_id: str
    target: str
    fused_findings: list[OSINTFinding] = field(default_factory=list)
    total_findings: int = 0
    unique_findings: int = 0
    conflicting_findings: int = 0
    fusion_confidence: float = 0.0
    entity_graph: dict = field(default_factory=dict)
    sources_used: list[str] = field(default_factory=list)


@dataclass
class CollectionReport:
    """Report on OSINT collection."""
    task_id: str
    target: str
    total_findings: int
    unique_findings: int
    sources_queried: int
    sources_successful: int
    sources_failed: int
    collection_time_ms: float
    findings_by_type: dict = field(default_factory=dict)
    findings_by_source: dict = field(default_factory=dict)


class DynamicOSINTCollector:
    """Dynamic OSINT collection framework."""

    def __init__(self):
        self._sources: dict[str, OSINTSource] = {}
        self._tasks: dict[str, CollectionTask] = {}
        self._findings: dict[str, OSINTFinding] = {}
        self._fusions: dict[str, DataFusionResult] = {}

        # Register default OSINT sources
        self._register_default_sources()

    def _register_default_sources(self):
        """Register default OSINT sources."""
        defaults = [
            ("web_search", "Web Search", "web", "https://api.search.com", 0.7, ["url", "domain", "email"]),
            ("twitter", "Twitter/X", "social", "https://api.twitter.com", 0.8, ["username", "email"]),
            ("github", "GitHub", "social", "https://api.github.com", 0.9, ["username", "email", "ip"]),
            ("dark_web", "Dark Web Monitor", "dark_web", "", 0.6, ["hash", "email", "url"]),
            ("crtsh", "Certificate Transparency", "ct_log", "https://crt.sh", 0.9, ["domain", "ip"]),
            ("whois", "WHOIS Database", "whois", "", 0.8, ["domain", "ip"]),
            ("shodan", "Shodan", "api", "https://api.shodan.io", 0.85, ["ip", "domain", "port"]),
            ("virustotal", "VirusTotal", "api", "https://api.virustotal.com", 0.9, ["hash", "url", "domain"]),
        ]

        for sid, name, stype, url, reliability, data in defaults:
            source = OSINTSource(
                source_id=hashlib.md5(
                    f"source:{sid}:{time.time()}".encode()
                ).hexdigest()[:12],
                name=name,
                source_type=stype,
                url=url,
                reliability=reliability,
                supported_data=data,
            )
            self._sources[source.source_id] = source

    def add_source(
        self,
        name: str,
        source_type: str,
        url: str = "",
        reliability: float = 0.5,
        rate_limit: float = 1.0,
    ) -> OSINTSource:
        """Add an OSINT source."""
        source = OSINTSource(
            source_id=hashlib.md5(
                f"source:{name}:{time.time()}".encode()
            ).hexdigest()[:12],
            name=name,
            source_type=source_type,
            url=url,
            reliability=reliability,
            rate_limit=rate_limit,
        )
        self._sources[source.source_id] = source
        return source

    def collect(
        self,
        target: str,
        target_type: str,
        source_ids: list[str] | None = None,
    ) -> dict:
        """Collect OSINT data for a target."""
        start = time.time()

        task = CollectionTask(
            task_id=hashlib.md5(
                f"task:{target}:{target_type}:{time.time()}".encode()
            ).hexdigest()[:12],
            target=target,
            target_type=target_type,
            sources=source_ids or list(self._sources.keys()),
            status="running",
            started_at=start,
        )
        self._tasks[task.task_id] = task

        findings = []
        for source_id in task.sources:
            source = self._sources.get(source_id)
            if not source or source.status != "available":
                task.errors.append(f"Source {source_id} not available")
                continue

            # Simulate collection
            collected = self._collect_from_source(source, target, target_type)
            findings.extend(collected)

            source.collection_count += 1
            source.last_collection = time.time()

        task.completed_at = time.time()
        task.results_count = len(findings)
        task.status = "completed"

        # Store findings
        for finding in findings:
            self._findings[finding.finding_id] = finding

        # Fuse data
        fusion = self._fuse_data(task.task_id, task.target, findings)

        return {
            "task_id": task.task_id,
            "target": task.target,
            "target_type": target_type,
            "status": task.status,
            "total_findings": len(findings),
            "unique_findings": len(set(f.value for f in findings)),
            "sources_queried": len(task.sources),
            "sources_successful": len(task.sources) - len(task.errors),
            "collection_time_ms": (time.time() - start) * 1000,
            "fusion_id": fusion.fusion_id,
            "fusion_confidence": fusion.fusion_confidence,
        }

    def _collect_from_source(
        self,
        source: OSINTSource,
        target: str,
        target_type: str,
    ) -> list[OSINTFinding]:
        """Collect data from a single source (simulated)."""
        findings = []

        # Simulate finding data based on source type and target
        for i in range(2 + (ord(hashlib.md5(f"{source.source_id}:{target}").encode()) % 5)):
            if source.source_type == "social":
                finding_type = "username"
                value = f"{target}_profile_{i}"
            elif source.source_type == "dark_web":
                finding_type = "hash" if target_type == "hash" else "email"
                value = f"{target}_dark_{i}@example.com"
            elif source.source_type == "ct_log":
                finding_type = "domain"
                value = f"subdomain{i}.{target}.com"
            elif source.source_type == "api":
                finding_type = "ip"
                value = f"192.168.{i}.{ord(hashlib.md5(target.encode()).hexdigest()[:2], 16) % 255}"
            else:
                finding_type = "domain"
                value = f"{target}_related_{i}.com"

            findings.append(OSINTFinding(
                finding_id=hashlib.md5(
                    f"finding:{source.source_id}:{target}:{i}:{time.time()}".encode()
                ).hexdigest()[:12],
                task_id="",  # Will be set by caller
                source=source.name,
                finding_type=finding_type,
                value=value,
                context=f"Found via {source.name}",
                timestamp=time.time(),
                confidence=source.reliability * (0.7 + (ord(hashlib.md5(f"{source.source_id}:{i}").encode()) % 30) / 100),
                reliability=source.reliability,
                metadata={"source_type": source.source_type, "target_type": target_type},
                related_to_target=True,
            ))

        return findings

    def _fuse_data(
        self,
        task_id: str,
        target: str,
        findings: list[OSINTFinding],
    ) -> DataFusionResult:
        """Fuse OSINT data from multiple sources."""
        # Deduplicate
        unique_values = set()
        unique_findings = []
        conflicts = 0

        for finding in findings:
            if finding.value not in unique_values:
                unique_values.add(finding.value)
                unique_findings.append(finding)
            else:
                conflicts += 1

        # Build entity graph
        entity_graph = {}
        for finding in unique_findings:
            if finding.value not in entity_graph:
                entity_graph[finding.value] = []
            entity_graph[finding.value].append(finding.source)

        # Calculate fusion confidence
        avg_reliability = sum(f.reliability for f in unique_findings) / max(1, len(unique_findings))
        avg_confidence = sum(f.confidence for f in unique_findings) / max(1, len(unique_findings))
        fusion_confidence = avg_reliability * avg_confidence

        fusion = DataFusionResult(
            fusion_id=hashlib.md5(
                f"fusion:{task_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            target=target,
            fused_findings=unique_findings,
            total_findings=len(findings),
            unique_findings=len(unique_findings),
            conflicting_findings=conflicts,
            fusion_confidence=fusion_confidence,
            entity_graph=entity_graph,
            sources_used=list(set(f.source for f in unique_findings)),
        )

        self._fusions[fusion.fusion_id] = fusion
        return fusion

    def assess_source_reliability(self, source_id: str) -> SourceReliability:
        """Assess reliability of an OSINT source."""
        source = self._sources.get(source_id)
        if not source:
            raise HTTPException(404, f"Source {source_id} not found")

        accuracy = source.reliability
        freshness = 1.0 if (time.time() - source.last_collection) < 86400 else 0.5
        completeness = 0.8 + (ord(hashlib.md5(source.source_id.encode()).hexdigest()[:1]) % 20) / 100
        error_rate = 1.0 - accuracy

        overall = (accuracy * 0.4 + freshness * 0.3 + completeness * 0.3)

        if overall > 0.8:
            recommendation = "Highly reliable, use as primary source"
        elif overall > 0.6:
            recommendation = "Reliable, use as secondary source"
        else:
            recommendation = "Low reliability, verify findings"

        return SourceReliability(
            source_id=source.source_id,
            name=source.name,
            overall_score=overall,
            accuracy=accuracy,
            freshness=freshness,
            completeness=completeness,
            error_rate=error_rate,
            recommendation=recommendation,
        )

    def get_report(self) -> dict:
        """Get OSINT collector report."""
        return {
            "total_sources": len(self._sources),
            "total_tasks": len(self._tasks),
            "total_findings": len(self._findings),
            "total_fusions": len(self._fusions),
            "sources_by_type": {
                t: sum(1 for s in self._sources.values() if s.source_type == t)
                for t in set(s.source_type for s in self._sources.values())
            },
            "sources": [
                {
                    "name": s.name,
                    "type": s.source_type,
                    "reliability": s.reliability,
                    "collections": s.collection_count,
                    "status": s.status,
                }
                for s in self._sources.values()
            ],
            "recent_tasks": [
                {
                    "target": t.target,
                    "type": t.target_type,
                    "findings": t.results_count,
                    "status": t.status,
                }
                for t in sorted(self._tasks.values(), key=lambda t: -t.completed_at)[:10]
            ],
        }


# Module-level singleton
osint_collector = DynamicOSINTCollector()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/intelex/osint/collect")
async def collect(payload: dict):
    """Collect OSINT data for a target."""
    return osint_collector.collect(
        target=payload["target"],
        target_type=payload["target_type"],
        source_ids=payload.get("source_ids", []),
    )


@router.get("/api/v1/intelex/osint/sources")
async def get_sources():
    """Get available OSINT sources."""
    return [
        {
            "source_id": s.source_id,
            "name": s.name,
            "type": s.source_type,
            "reliability": s.reliability,
            "supported_data": s.supported_data,
        }
        for s in osint_collector._sources.values()
    ]


@router.get("/api/v1/intelex/osint/sources/{source_id}/reliability")
async def assess_source_reliability(source_id: str):
    """Assess source reliability."""
    return osint_collector.assess_source_reliability(source_id).__dict__


@router.get("/api/v1/intelex/osint/report")
async def get_report():
    """Get OSINT collector report."""
    return osint_collector.get_report()
