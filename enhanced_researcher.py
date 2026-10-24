"""
IntelX/enhanced_researcher.py — IntelX Enhanced Multi-Source Research Engine.

Extends IntelX's research capabilities with:
1. Multi-Source Synthesis: combines results from multiple research methods
2. Cross-Reference Verification: validates claims across sources
3. Bias Detection: identifies potential bias in research sources
4. Citation Graph: builds a citation knowledge graph
5. Temporal Analysis: tracks how information changes over time
6. Conflict Resolution: detects and flags conflicting information
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResearchClaim:
    """A single research claim with provenance."""
    claim_id: str
    statement: str
    source_ids: list[str]
    confidence: float
    timestamp: float
    entities: list[str] = field(default_factory=list)
    sentiment: float = 0.0


@dataclass
class CrossReferenceResult:
    """Result of cross-referencing claims."""
    claim_id: str
    supporting_sources: list[str]
    contradicting_sources: list[str]
    agreement_score: float
    conflict_flag: bool


@dataclass
class BiasAnalysis:
    """Bias analysis for a source."""
    source_id: str
    bias_score: float
    bias_types: list[str]
    evidence: list[str]


@dataclass
class CitationNode:
    """A node in the citation graph."""
    claim_id: str
    cited_by: list[str]
    cited_count: int
    authority_score: float
    influence_score: float


class EnhancedResearcher:
    """Enhanced research engine with multi-source synthesis and verification."""

    def __init__(self):
        self._claims: dict[str, ResearchClaim] = {}
        self._citation_graph: dict[str, CitationNode] = {}
        self._source_bias: dict[str, BiasAnalysis] = {}
        self._temporal_snapshots: dict[str, list[dict]] = {}
        self._conflicts: list[dict] = []

    # ── Multi-Source Synthesis ─────────────────────────────────────────────

    def synthesize(
        self,
        topic: str,
        sources: list[dict],
    ) -> dict[str, Any]:
        """Synthesize information from multiple sources."""
        if not sources:
            return {"topic": topic, "status": "NO_SOURCES"}

        synthesized = {
            "topic": topic,
            "synthesis": "",
            "key_claims": [],
            "source_count": len(sources),
            "agreement": 0.0,
            "conflicts": [],
        }

        # Extract and score claims from each source
        all_claims: list[ResearchClaim] = []
        for source in sources:
            claims = self._extract_claims(source, topic)
            all_claims.extend(claims)

        if not all_claims:
            synthesized["status"] = "NO_CLAIMS"
            return synthesized

        # Group claims by similarity
        clusters = self._cluster_claims(all_claims)

        # Build synthesis from top clusters
        synthesis_parts = []
        for cluster in clusters[:5]:
            if cluster:
                statement = cluster[0].statement
                confidence = sum(c.confidence for c in cluster) / len(cluster)
                synthesis_parts.append({
                    "statement": statement,
                    "confidence": confidence,
                    "supporting_claims": len(cluster),
                })

        synthesized["key_claims"] = synthesis_parts
        synthesized["synthesis"] = " ".join(
            s["statement"] for s in synthesis_parts[:3]
        )

        # Calculate agreement
        if len(clusters) > 1:
            total_claims = len(all_claims)
            largest = len(max(clusters, key=len)) if clusters else 0
            synthesized["agreement"] = largest / total_claims if total_claims > 0 else 0.0

        # Check for conflicts
        conflicts = self._detect_conflicts(all_claims)
        synthesized["conflicts"] = conflicts
        synthesized["conflict_flag"] = len(conflicts) > 0

        return synthesized

    def _extract_claims(self, source: dict, topic: str) -> list[ResearchClaim]:
        """Extract atomic claims from a source document."""
        claims = []
        text = source.get("text", "")
        source_id = source.get("id", hashlib.md5(text.encode()).hexdigest()[:12])

        # Split into sentences
        sentences = re.split(r'[.!?]+', text)

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if len(sentence) < 20 or len(sentence) > 500:
                continue

            # Skip sentences that don't relate to topic
            if topic.lower() not in sentence.lower() and not any(
                w in sentence.lower() for w in topic.lower().split()
            ):
                continue

            claim_id = hashlib.md5(
                f"{source_id}:{i}:{sentence}".encode()
            ).hexdigest()[:12]

            entities = self._extract_entities(sentence)
            sentiment = self._sentiment(sentence)

            claim = ResearchClaim(
                claim_id=claim_id,
                statement=sentence,
                source_ids=[source_id],
                confidence=min(1.0, 0.5 + len(entities) * 0.1),
                timestamp=time.time(),
                entities=entities,
                sentiment=sentiment,
            )

            self._claims[claim_id] = claim
            claims.append(claim)

        return claims

    def _extract_entities(self, text: str) -> list[str]:
        """Extract named entities from text."""
        entities = []

        # Capitalized words (basic NER)
        caps = re.findall(r'\b[A-Z][a-zA-Z]{2,}\b', text)
        entities.extend([c for c in caps if c not in ("The", "This", "That", "Those", "These", "There")])

        # Numbers
        nums = re.findall(r'\b\d+[%.]?\b', text)
        entities.extend(nums[:3])

        return list(set(entities))[:5]

    def _sentiment(self, text: str) -> float:
        """Simple sentiment analysis."""
        positive = ["good", "great", "excellent", "success", "improve", "increase", "growth", "benefit", "positive", "win"]
        negative = ["bad", "poor", "failure", "decline", "decrease", "risk", "problem", "issue", "negative", "lose", "lose"]

        pos = sum(1 for w in positive if w in text.lower())
        neg = sum(1 for w in negative if w in text.lower())

        if pos + neg == 0:
            return 0.0
        return (pos - neg) / (pos + neg)

    def _cluster_claims(self, claims: list[ResearchClaim]) -> list[list[ResearchClaim]]:
        """Cluster similar claims together."""
        clusters: list[list[ResearchClaim]] = []

        for claim in claims:
            placed = False
            for cluster in clusters:
                if self._similar(claim, cluster[0]) > 0.6:
                    cluster.append(claim)
                    placed = True
                    break
            if not placed:
                clusters.append([claim])

        return sorted(clusters, key=len, reverse=True)

    def _similar(self, c1: ResearchClaim, c2: ResearchClaim) -> float:
        """Calculate similarity between two claims."""
        # Word overlap
        w1 = set(c1.statement.lower().split())
        w2 = set(c2.statement.lower().split())
        if not w1 or not w2:
            return 0.0

        overlap = len(w1 & w2) / max(len(w1), len(w2))

        # Entity overlap
        e1 = set(c1.entities)
        e2 = set(c2.entities)
        entity_overlap = len(e1 & e2) / max(len(e1), len(e2), 1)

        # Sentiment alignment
        sentiment_align = 1.0 - abs(c1.sentiment - c2.sentiment)

        return (overlap * 0.5 + entity_overlap * 0.3 + sentiment_align * 0.2)

    def _detect_conflicts(self, claims: list[ResearchClaim]) -> list[dict]:
        """Detect conflicting claims."""
        conflicts = []

        for i, c1 in enumerate(claims):
            for c2 in claims[i+1:]:
                if c1.source_ids == c2.source_ids:
                    continue

                similarity = self._similar(c1, c2)

                # High similarity but opposite sentiment = potential conflict
                if similarity > 0.7 and abs(c1.sentiment - c2.sentiment) > 0.5:
                    conflict = {
                        "claim_a": c1.statement[:100],
                        "claim_b": c2.statement[:100],
                        "sources_a": c1.source_ids,
                        "sources_b": c2.source_ids,
                        "similarity": similarity,
                        "sentiment_diff": abs(c1.sentiment - c2.sentiment),
                    }
                    conflicts.append(conflict)
                    self._conflicts.append(conflict)

        return conflicts

    # ── Cross-Reference Verification ────────────────────────────────────────

    def cross_reference(self, claim_id: str) -> CrossReferenceResult:
        """Cross-reference a claim across all sources."""
        claim = self._claims.get(claim_id)
        if not claim:
            return CrossReferenceResult(
                claim_id=claim_id,
                supporting_sources=[],
                contradicting_sources=[],
                agreement_score=0.0,
                conflict_flag=False,
            )

        supporting = list(claim.source_ids)
        contradicting = []

        # Find claims that contradict
        for other_id, other in self._claims.items():
            if other_id == claim_id:
                continue
            if other.source_ids == claim.source_ids:
                continue

            similarity = self._similar(claim, other)
            if similarity > 0.5 and abs(claim.sentiment - other.sentiment) > 0.4:
                contradicting.extend(other.source_ids)

        agreement = len(supporting) / (len(supporting) + len(contradicting) + 1)

        result = CrossReferenceResult(
            claim_id=claim_id,
            supporting_sources=list(set(supporting)),
            contradicting_sources=list(set(contradicting)),
            agreement_score=agreement,
            conflict_flag=len(contradicting) > 0,
        )

        return result

    # ── Bias Detection ─────────────────────────────────────────────────────

    def analyze_bias(self, source: dict) -> BiasAnalysis:
        """Analyze potential bias in a source."""
        text = source.get("text", "")
        source_id = source.get("id", hashlib.md5(text.encode()).hexdigest()[:12])

        bias_types = []
        evidence = []
        bias_score = 0.0

        # Load-bearing language
        load_bearing = ["obviously", "clearly", "everyone knows", "without doubt", "undeniable", "proven"]
        lb_count = sum(1 for w in load_bearing if w in text.lower())
        if lb_count > 2:
            bias_types.append("load_bearing_language")
            evidence.append(f"Found {lb_count} instances of load-bearing language")
            bias_score += lb_count * 0.1

        # Emotional language
        emotional = ["shocking", "terrible", "amazing", "disgusting", "unbelievable", "horrible"]
        em_count = sum(1 for w in emotional if w in text.lower())
        if em_count > 2:
            bias_types.append("emotional_language")
            evidence.append(f"Found {em_count} instances of emotional language")
            bias_score += em_count * 0.1

        # One-sided framing
        if text.count("however") == 0 and text.count("although") == 0 and len(text) > 500:
            bias_types.append("one_sided")
            evidence.append("No counterarguments present")
            bias_score += 0.2

        # Source type bias
        source_type = source.get("type", "")
        if source_type == "opinion":
            bias_types.append("opinion_source")
            evidence.append("Source is opinion-based, not factual reporting")
            bias_score += 0.3

        bias_score = min(1.0, bias_score)

        analysis = BiasAnalysis(
            source_id=source_id,
            bias_score=bias_score,
            bias_types=bias_types,
            evidence=evidence,
        )

        self._source_bias[source_id] = analysis
        return analysis

    # ── Citation Graph ─────────────────────────────────────────────────────

    def build_citation_graph(self) -> dict[str, CitationNode]:
        """Build a citation knowledge graph."""
        self._citation_graph = {}

        # Count citations
        cited_by: dict[str, list[str]] = {}
        for claim_id, claim in self._claims.items():
            for src in claim.source_ids:
                if src not in cited_by:
                    cited_by[src] = []
                cited_by[src].append(claim_id)

        # Build nodes
        for claim_id, claim in self._claims.items():
            cited_count = len(cited_by.get(claim_id, []))

            # Authority score: based on confidence and entities
            authority = claim.confidence * (1.0 + len(claim.entities) * 0.1)

            # Influence score: based on citations
            influence = math.log(1 + cited_count)

            node = CitationNode(
                claim_id=claim_id,
                cited_by=cited_by.get(claim_id, []),
                cited_count=cited_count,
                authority_score=authority,
                influence_score=influence,
            )

            self._citation_graph[claim_id] = node

        return self._citation_graph

    # ── Temporal Analysis ───────────────────────────────────────────────────

    def snapshot_topic(self, topic: str, claims: list[ResearchClaim]) -> dict:
        """Take a temporal snapshot of claims about a topic."""
        snapshot = {
            "topic": topic,
            "timestamp": time.time(),
            "claim_count": len(claims),
            "avg_confidence": sum(c.confidence for c in claims) / len(claims) if claims else 0,
            "avg_sentiment": sum(c.sentiment for c in claims) / len(claims) if claims else 0,
        }

        if topic not in self._temporal_snapshots:
            self._temporal_snapshots[topic] = []

        self._temporal_snapshots[topic].append(snapshot)

        return snapshot

    def get_temporal_trend(self, topic: str) -> dict[str, Any]:
        """Get temporal trend for a topic."""
        snapshots = self._temporal_snapshots.get(topic, [])

        if len(snapshots) < 2:
            return {"status": "INSUFFICIENT_DATA", "snapshots": len(snapshots)}

        confidence_trend = []
        sentiment_trend = []

        for snap in snapshots:
            confidence_trend.append(snap["avg_confidence"])
            sentiment_trend.append(snap["avg_sentiment"])

        # Calculate trend direction
        conf_diff = confidence_trend[-1] - confidence_trend[0]
        sent_diff = sentiment_trend[-1] - sentiment_trend[0]

        return {
            "topic": topic,
            "snapshots": len(snapshots),
            "confidence_trend": "rising" if conf_diff > 0.05 else "falling" if conf_diff < -0.05 else "stable",
            "sentiment_trend": "positive" if sent_diff > 0.1 else "negative" if sent_diff < -0.1 else "neutral",
            "confidence_change": conf_diff,
            "sentiment_change": sent_diff,
        }

    # ── Conflict Resolution ─────────────────────────────────────────────────

    def resolve_conflicts(self) -> list[dict]:
        """Resolve detected conflicts."""
        resolved = []

        for conflict in self._conflicts:
            # Weight by source authority
            authority_a = self._source_bias.get(conflict["sources_a"][0], None)
            authority_b = self._source_bias.get(conflict["sources_b"][0], None)

            bias_a = authority_a.bias_score if authority_a else 0.0
            bias_b = authority_b.bias_score if authority_b else 0.0

            resolution = {
                "conflict": conflict,
                "resolution": "trust_a" if bias_a < bias_b else "trust_b",
                "trusted_source": conflict["sources_a"] if bias_a < bias_b else conflict["sources_b"],
                "reason": f"Source A bias: {bias_a:.2f}, Source B bias: {bias_b:.2f}",
            }

            resolved.append(resolution)

        return resolved

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_research_report(self) -> dict[str, Any]:
        """Generate a comprehensive research report."""
        return {
            "total_claims": len(self._claims),
            "total_conflicts": len(self._conflicts),
            "citation_graph_size": len(self._citation_graph),
            "bias_analyses": len(self._source_bias),
            "temporal_topics": list(self._temporal_snapshots.keys()),
        }
