"""INTELX Source Quality Scoring, Authority Ranking, and Freshness Estimation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class SourceScore:
    """Multi-dimensional quality score for an ingested research source."""

    authority: float
    relevance: float
    freshness: float
    independence: float
    accessibility: float
    total: float


PRIMARY_HINTS = (
    "gov",
    "edu",
    "who.int",
    "un.org",
    "sec.gov",
    "europa.eu",
    "arxiv.org",
    "nature.com",
)
LOW_QUALITY_HINTS = ("pinterest", "quora", "forums", "aggregator", "unknown", "spam")


def _matches_domain_or_subdomain(host: str, domain: str) -> bool:
    """Match an exact DNS name or its subdomains, never an arbitrary substring."""
    normalized_host = host.rstrip(".").lower()
    normalized_domain = domain.rstrip(".").lower()
    return normalized_host == normalized_domain or normalized_host.endswith(
        "." + normalized_domain
    )


class SourceQuality:
    """Computes transparent, inspectable source credibility and ranking metrics."""

    def score(
        self,
        url: str,
        title: str,
        snippet: str,
        query_terms: set[str],
        published_age_days: float | None = None,
        duplicate_count: int = 0,
    ) -> SourceScore:
        """Calculate weighted quality score across 5 core dimensions."""
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        authority = 0.55
        if any(_matches_domain_or_subdomain(host, hint) for hint in PRIMARY_HINTS):
            authority += 0.30
        if set(host.split(".")) & set(LOW_QUALITY_HINTS):
            authority -= 0.20

        text = (title + " " + snippet).lower()
        matched = sum(1 for t in query_terms if t.lower() in text)
        relevance = min(1.0, matched / max(1, len(query_terms)))

        if published_age_days is None:
            # Unknown age is not evidence that a source is maximally fresh.
            freshness = 0.5
        else:
            try:
                age_days = float(published_age_days)
            except (TypeError, ValueError):
                freshness = 0.0
            else:
                freshness = (
                    math.exp(-age_days / 3650)
                    if math.isfinite(age_days) and age_days >= 0
                    else 0.0
                )
        independence = 1.0 / (1.0 + duplicate_count * 0.5)
        accessibility = 0.95 if url.startswith(("https://", "http://")) else 0.60

        total = round(
            max(
                0.0,
                min(
                    1.0,
                    0.35 * authority
                    + 0.30 * relevance
                    + 0.15 * freshness
                    + 0.15 * independence
                    + 0.05 * accessibility,
                ),
            ),
            4,
        )
        return SourceScore(
            authority=authority,
            relevance=relevance,
            freshness=freshness,
            independence=independence,
            accessibility=accessibility,
            total=total,
        )

    def rank(self, sources: list[Any], query_terms: list[str]) -> list[Any]:
        """Rank source candidates by computed total quality score descending."""
        term_set = set(query_terms)
        return sorted(
            sources,
            key=lambda s: (
                self.score(
                    getattr(s, "url", getattr(s, "location", "")),
                    getattr(s, "title", ""),
                    getattr(s, "snippet", ""),
                    term_set,
                ).total
            ),
            reverse=True,
        )

    def normalize_title(self, title: str) -> str:
        """Clean and normalize title string."""
        return re.sub(r"\s+", " ", title).strip().lower()

    def quality_bucket(self, score: float) -> str:
        """Classify score into human-readable quality tiers."""
        if score >= 0.80:
            return "high"
        if score >= 0.60:
            return "medium"
        return "low"
