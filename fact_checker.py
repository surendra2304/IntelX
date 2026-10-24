"""
IntelX/fact_checker.py — IntelX Fact-Checking Pipeline.

Extends IntelX's capabilities with:
1. Claim Extraction: extract atomic claims from text
2. Evidence Search: find supporting and contradicting evidence
3. Claim Verdict: classify claims as true, false, or partially true
4. Source Reliability Scoring: score source reliability
5. Fact-Check Report: generate comprehensive fact-check reports
6. Trend Tracking: track how fact-check verdicts change over time
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Claim:
    """An extracted claim."""
    claim_id: str
    statement: str
    subject: str
    predicate: str
    object: str
    polarity: str  # positive, negative, neutral
    confidence: float
    extracted_at: float = 0.0


@dataclass
class Evidence:
    """Evidence for or against a claim."""
    claim_id: str
    source_id: str
    source_name: str
    source_reliability: float
    text: str
    supports: bool
    relevance: float
    published_at: float = 0.0


@dataclass
class Verdict:
    """A fact-check verdict."""
    claim_id: str
    statement: str
    verdict: str  # true, mostly_true, half_true, mostly_false, false
    confidence: float
    supporting_evidence: list[Evidence]
    contradicting_evidence: list[Evidence]
    reasoning: str
    checked_at: float = 0.0


@dataclass
class FactCheckReport:
    """A comprehensive fact-check report."""
    report_id: str
    claim_count: int
    true_count: int
    false_count: int
    partially_true_count: int
    unverified_count: int
    avg_confidence: float
    sources_checked: int
    created_at: float = 0.0


class FactChecker:
    """Fact-checking pipeline."""

    def __init__(self):
        self._claims: dict[str, Claim] = {}
        self._verdicts: dict[str, Verdict] = {}
        self._reports: list[FactCheckReport] = []
        self._source_reliability: dict[str, float] = {}

    # ── Claim Extraction ────────────────────────────────────────────────────

    def extract_claims(self, text: str) -> list[Claim]:
        """Extract atomic claims from text."""
        claims = []

        # Split into sentences
        sentences = re.split(r'[.!?]+', text)

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if len(sentence) < 10 or len(sentence) > 500:
                continue

            # Extract subject-predicate-object
            parts = sentence.split()
            if len(parts) < 3:
                continue

            subject = parts[0]
            predicate = parts[1] if len(parts) > 1 else ""
            obj = " ".join(parts[2:5]) if len(parts) > 2 else ""

            # Determine polarity
            negative_words = {"not", "never", "no", "false", "wrong", "bad"}
            polarity = "neutral"
            if any(w in sentence.lower() for w in negative_words):
                polarity = "negative"
            elif any(w in predicate.lower() for w in ["is", "are", "has", "have"]):
                polarity = "positive"

            claim = Claim(
                claim_id=hashlib.md5(
                    f"{sentence}:{time.time()}".encode()
                ).hexdigest()[:12],
                statement=sentence,
                subject=subject,
                predicate=predicate,
                object=obj,
                polarity=polarity,
                confidence=0.8 if len(sentence) < 200 else 0.6,
                extracted_at=time.time(),
            )

            self._claims[claim.claim_id] = claim
            claims.append(claim)

        return claims

    # ── Evidence Search ──────────────────────────────────────────────────────

    def find_evidence(
        self,
        claim: Claim,
        sources: list[dict],
    ) -> list[Evidence]:
        """Find evidence for or against a claim."""
        supporting = []
        contradicting = []

        for source in sources:
            text = source.get("text", "").lower()
            claim_lower = claim.statement.lower()

            # Check if source mentions the claim
            claim_words = set(claim_lower.split())
            source_words = set(text.split())

            overlap = claim_words & source_words
            if len(overlap) < 3:
                continue

            # Determine if supports or contradicts
            source_reliability = source.get("reliability", 0.5)
            relevance = len(overlap) / max(1, len(claim_words))

            # Check sentiment
            positive = source.get("sentiment", 0.0)
            supports = (claim.polarity == "positive" and positive > 0) or \
                       (claim.polarity == "negative" and positive < 0) or \
                       (claim.polarity == "neutral")

            evidence = Evidence(
                claim_id=claim.claim_id,
                source_id=source.get("id", "unknown"),
                source_name=source.get("name", "Unknown"),
                source_reliability=source_reliability,
                text=source.get("text", "")[:200],
                supports=supports,
                relevance=relevance,
                published_at=source.get("published_at", 0.0),
            )

            if supports:
                supporting.append(evidence)
            else:
                contradicting.append(evidence)

        return supporting + contradicting

    # ── Claim Verdict ───────────────────────────────────────────────────────

    def check_claim(
        self,
        claim: Claim,
        sources: list[dict],
    ) -> Verdict:
        """Check a claim and return a verdict."""
        evidence = self.find_evidence(claim, sources)

        supporting = [e for e in evidence if e.supports]
        contradicting = [e for e in evidence if not e.supports]

        # Weight by source reliability
        support_score = sum(
            e.source_reliability * e.relevance for e in supporting
        )
        contradict_score = sum(
            e.source_reliability * e.relevance for e in contradicting
        )

        # Determine verdict
        total_evidence = support_score + contradict_score

        if total_evidence == 0:
            verdict = "unverified"
            confidence = 0.0
            reasoning = "No evidence found to verify this claim"
        elif support_score > contradict_score * 2:
            verdict = "true"
            confidence = min(0.9, support_score / total_evidence)
            reasoning = f"Strong evidence supports this claim ({len(supporting)} sources)"
        elif support_score > contradict_score * 1.5:
            verdict = "mostly_true"
            confidence = min(0.8, support_score / total_evidence)
            reasoning = "Most evidence supports this claim"
        elif abs(support_score - contradict_score) < 0.2 * total_evidence:
            verdict = "half_true"
            confidence = 0.5
            reasoning = "Mixed evidence - both supporting and contradicting sources found"
        elif contradict_score > support_score * 1.5:
            verdict = "mostly_false"
            confidence = min(0.8, contradict_score / total_evidence)
            reasoning = "Most evidence contradicts this claim"
        else:
            verdict = "false"
            confidence = min(0.9, contradict_score / total_evidence)
            reasoning = f"Strong evidence contradicts this claim ({len(contradicting)} sources)"

        result = Verdict(
            claim_id=claim.claim_id,
            statement=claim.statement,
            verdict=verdict,
            confidence=confidence,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            reasoning=reasoning,
            checked_at=time.time(),
        )

        self._verdicts[claim.claim_id] = result
        return result

    # ── Source Reliability Scoring ───────────────────────────────────────────

    def score_source_reliability(
        self,
        source_id: str,
        source_type: str,
        history: list[dict],
    ) -> float:
        """Score a source's reliability."""
        base_score = 0.5

        # Source type adjustments
        if source_type == "academic":
            base_score += 0.2
        elif source_type == "government":
            base_score += 0.15
        elif source_type == "news":
            base_score += 0.05
        elif source_type == "social":
            base_score -= 0.1
        elif source_type == "opinion":
            base_score -= 0.15

        # Adjust based on history
        if history:
            accuracy = sum(h.get("accuracy", 0.5) for h in history) / len(history)
            base_score = base_score * 0.5 + accuracy * 0.5

        base_score = max(0.0, min(1.0, base_score))
        self._source_reliability[source_id] = base_score
        return base_score

    # ── Fact-Check Report ───────────────────────────────────────────────────

    def generate_report(
        self,
        claims: list[Claim] | None = None,
    ) -> FactCheckReport:
        """Generate a fact-check report."""
        claims = claims or list(self._claims.values())

        if not claims:
            return FactCheckReport(
                report_id=hashlib.md5(f"report:{time.time()}".encode()).hexdigest()[:12],
                claim_count=0,
                true_count=0,
                false_count=0,
                partially_true_count=0,
                unverified_count=0,
                avg_confidence=0.0,
                sources_checked=0,
                created_at=time.time(),
            )

        true_count = 0
        false_count = 0
        partially_true_count = 0
        unverified_count = 0
        total_confidence = 0.0
        sources_checked = set()

        for claim in claims:
            verdict = self._verdicts.get(claim.claim_id)
            if verdict:
                if verdict.verdict == "true":
                    true_count += 1
                elif verdict.verdict in ("mostly_false", "false"):
                    false_count += 1
                elif verdict.verdict in ("half_true", "mostly_true"):
                    partially_true_count += 1
                else:
                    unverified_count += 1

                total_confidence += verdict.confidence

                for ev in verdict.supporting_evidence + verdict.contradicting_evidence:
                    sources_checked.add(ev.source_id)

        report = FactCheckReport(
            report_id=hashlib.md5(f"report:{time.time()}".encode()).hexdigest()[:12],
            claim_count=len(claims),
            true_count=true_count,
            false_count=false_count,
            partially_true_count=partially_true_count,
            unverified_count=unverified_count,
            avg_confidence=total_confidence / max(1, len(claims)),
            sources_checked=len(sources_checked),
            created_at=time.time(),
        )

        self._reports.append(report)
        return report

    # ── Trend Tracking ──────────────────────────────────────────────────────

    def track_verdict_trends(
        self,
        claim_pattern: str,
        time_window: float = 86400.0,
    ) -> list[dict]:
        """Track how verdicts for similar claims change over time."""
        cutoff = time.time() - time_window

        trends = []
        for claim_id, verdict in self._verdicts.items():
            claim = self._claims.get(claim_id)
            if not claim:
                continue

            if claim_pattern.lower() not in claim.statement.lower():
                continue

            if verdict.checked_at < cutoff:
                continue

            trends.append({
                "claim_id": claim_id,
                "statement": claim.statement,
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "checked_at": verdict.checked_at,
            })

        return trends

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_fact_check_report(self) -> dict[str, Any]:
        """Generate a fact-check summary."""
        return {
            "total_claims": len(self._claims),
            "total_verdicts": len(self._verdicts),
            "total_reports": len(self._reports),
            "sources_scored": len(self._source_reliability),
            "latest_report": self._reports[-1].__dict__ if self._reports else None,
        }
