"""
intelx/agents/synthesis_engine.py — IntelX Deep Research Synthesis Engine.

Enhances IntelX with:
1. Multi-Source Evidence Aggregation: Combines findings from multiple sources
2. Contradiction Detection: Identifies conflicting claims across sources
3. Confidence Scoring: Rates each claim based on source quality and corroboration
4. Timeline Construction: Builds chronological event timelines
5. Knowledge Gap Identification: Identifies missing information
6. Citation Provenance: Tracks exact source for every claim
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from intelx.agents.base import BaseAgent
from intelx.agents.citations import CitationManager
from intelx.agents.contradictions import ContradictionDetector
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


@dataclass
class EvidenceItem:
    """A piece of evidence with provenance and confidence."""
    claim: str
    source_url: str
    source_title: str = ""
    source_quality: float = 0.5  # 0-1, based on source reputation
    corroboration_count: int = 1
    confidence: float = 0.0
    timestamp: str = ""
    evidence_type: str = "text"  # text, image, data, etc.


@dataclass
class SynthesisResult:
    """Result of deep research synthesis."""
    summary: str
    key_findings: list[str] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    knowledge_gaps: list[str] = field(default_factory=list)
    confidence: float = 0.0
    citations: list[dict[str, Any]] = field(default_factory=list)
    sources_analyzed: int = 0
    claims_extracted: int = 0


class SynthesisEngine:
    """Deep research synthesis engine for IntelX."""

    def __init__(self, model_gateway: ModelGateway | None = None):
        self.gateway = model_gateway or ModelGateway()
        self.citations = CitationManager()
        self.contradiction_detector = ContradictionDetector()

    async def synthesize_research(
        self,
        query: str,
        sources: list[dict[str, Any]] | None = None,
        max_sources: int = 20,
    ) -> SynthesisResult:
        """
        Synthesize research from multiple sources.

        Args:
            query: Research question or topic
            sources: List of source documents with content
            max_sources: Maximum number of sources to analyze

        Returns:
            SynthesisResult with findings, timeline, contradictions, etc.
        """
        logger.info(f"Synthesizing research: {query[:80]}")

        # Step 1: Gather evidence from sources
        evidence_items: list[EvidenceItem] = []

        if sources:
            for source in sources[:max_sources]:
                evidence = self._extract_evidence(source, query)
                evidence_items.extend(evidence)
        else:
            # In production, this would crawl/search for sources
            evidence_items = await self._gather_evidence(query, max_sources)

        # Step 2: Score evidence by corroboration
        scored_evidence = self._score_evidence(evidence_items)

        # Step 3: Detect contradictions
        contradictions = self.contradiction_detector.detect(scored_evidence)

        # Step 4: Build timeline
        timeline = self._build_timeline(scored_evidence)

        # Step 5: Identify knowledge gaps
        gaps = self._identify_gaps(scored_evidence, contradictions)

        # Step 6: Generate summary
        summary = await self._generate_summary(query, scored_evidence, contradictions)

        # Step 7: Calculate overall confidence
        confidence = self._calculate_confidence(scored_evidence, contradictions)

        result = SynthesisResult(
            summary=summary,
            key_findings=self._extract_key_findings(scored_evidence),
            timeline=timeline,
            contradictions=contradictions,
            knowledge_gaps=gaps,
            confidence=confidence,
            citations=self.citations.get_citations(scored_evidence),
            sources_analyzed=len(scored_evidence),
            claims_extracted=len(scored_evidence),
        )

        logger.info(f"Synthesis complete: {result.sources_analyzed} sources, confidence={result.confidence:.2f}")
        return result

    def _extract_evidence(self, source: dict[str, Any], query: str) -> list[EvidenceItem]:
        """Extract evidence items from a source document."""
        evidence: list[EvidenceItem] = []

        content = source.get("content", "")
        url = source.get("url", "")
        title = source.get("title", "")
        quality = source.get("quality", 0.5)

        # Split content into sentences/claims
        sentences = re.split(r'(?<=[.!?])\s+', content)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20 or len(sentence) > 500:
                continue

            # Simple relevance check
            query_words = set(query.lower().split())
            sentence_words = set(sentence.lower().split())
            overlap = len(query_words & sentence_words)

            if overlap > 0 or len(sentence_words) < 5:
                evidence.append(EvidenceItem(
                    claim=sentence,
                    source_url=url,
                    source_title=title,
                    source_quality=quality,
                    evidence_type="text",
                ))

        return evidence

    async def _gather_evidence(self, query: str, max_sources: int) -> list[EvidenceItem]:
        """Gather evidence by searching and crawling sources."""
        # In production, this would use search engines and crawlers
        # For now, return empty list (agent will use provided sources)
        return []

    def _score_evidence(self, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
        """Score evidence by corroboration and source quality."""
        # Group similar claims
        claim_groups: dict[str, list[EvidenceItem]] = {}

        for item in evidence:
            # Hash the claim for grouping
            claim_hash = hashlib.md5(item.claim.lower().strip().encode()).hexdigest()
            claim_groups.setdefault(claim_hash, []).append(item)

        # Score by corroboration
        scored: list[EvidenceItem] = []

        for claim_hash, group in claim_groups.items():
            # Count corroborating sources
            unique_sources = set(item.source_url for item in group)
            corroboration = len(unique_sources)

            # Average source quality
            avg_quality = sum(item.source_quality for item in group) / len(group)

            # Confidence score: corroboration * quality
            confidence = min(1.0, (corroboration / 5.0) * avg_quality * 1.2)

            for item in group:
                item.corroboration_count = corroboration
                item.confidence = confidence
                scored.append(item)

        # Sort by confidence
        return sorted(scored, key=lambda e: e.confidence, reverse=True)

    def _build_timeline(self, evidence: list[EvidenceItem]) -> list[dict[str, Any]]:
        """Build a chronological timeline from evidence."""
        timeline_entries = []

        for item in evidence:
            # Extract date if present
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', item.timestamp or item.claim)
            date_str = date_match.group(1) if date_match else datetime.now(timezone.utc).isoformat()

            timeline_entries.append({
                "date": date_str,
                "event": item.claim[:200],
                "source": item.source_url,
                "confidence": item.confidence,
            })

        # Sort by date
        return sorted(timeline_entries, key=lambda e: e["date"])

    def _identify_gaps(self, evidence: list[EvidenceItem], contradictions: list[dict]) -> list[str]:
        """Identify knowledge gaps in the research."""
        gaps = []

        if not evidence:
            gaps.append("No evidence found for this query")

        if contradictions:
            gaps.append(f"{len(contradictions)} contradictions detected between sources")

        # Check for missing information
        low_confidence = [e for e in evidence if e.confidence < 0.3]
        if low_confidence:
            gaps.append(f"{len(low_confidence)} claims have low confidence and need verification")

        return gaps

    async def _generate_summary(
        self,
        query: str,
        evidence: list[EvidenceItem],
        contradictions: list[dict],
    ) -> str:
        """Generate a summary of the research findings."""
        # Use model gateway to generate summary
        top_evidence = evidence[:10]

        evidence_text = "\n".join(
            f"[{e.confidence:.2f}] {e.claim} (Source: {e.source_title})"
            for e in top_evidence
        )

        contradiction_text = ""
        if contradictions:
            contradiction_text = "\n\nContradictions detected:\n" + "\n".join(
                f"- {c.get('claim1', '')} vs {c.get('claim2', '')}"
                for c in contradictions[:3]
            )

        prompt = f"""Research Query: {query}

Evidence Found:
{evidence_text}
{contradiction_text}

Please provide a comprehensive summary of the findings, noting any contradictions or uncertainties."""

        try:
            response = await self.gateway.generate(
                prompt=prompt,
                task="synthesis",
            )
            return response.text if hasattr(response, 'text') else str(response)
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            # Fallback: simple concatenation
            return "\n".join(e.claim for e in top_evidence[:5])

    def _extract_key_findings(self, evidence: list[EvidenceItem]) -> list[str]:
        """Extract key findings from evidence."""
        return [e.claim[:150] for e in evidence[:5]]

    def _calculate_confidence(self, evidence: list[EvidenceItem], contradictions: list[dict]) -> float:
        """Calculate overall confidence in the synthesis."""
        if not evidence:
            return 0.0

        avg_confidence = sum(e.confidence for e in evidence) / len(evidence)

        # Penalize for contradictions
        contradiction_penalty = min(0.3, len(contradictions) * 0.1)

        return max(0.0, avg_confidence - contradiction_penalty)
