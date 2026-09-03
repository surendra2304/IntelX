"""INTELX Scout Agent: Multi-Angle Query Portfolio Discovery and Source Quality Ranking."""

import logging
import urllib.parse
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.base import BaseAgent
from intelx.agents.planner import Plan
from intelx.agents.query_planner import QueryPortfolioPlanner
from intelx.connectors.base import default_policy_guard
from intelx.connectors.search import WebSearchConnector
from intelx.connectors.source_quality import SourceQuality
from intelx.core.settings import get_settings
from intelx.db.repos import ClaimRepo
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class SourceCandidate(BaseModel):
    """Potential evidence source identified for retrieval."""

    location: str
    title: str
    reason: str
    expected_relevance: float = Field(default=0.8, ge=0.0, le=1.0)
    snippet: str | None = None


class ScoutOutput(BaseModel):
    """Collection of ranked source candidates for a subquestion."""

    candidates: list[SourceCandidate] = Field(default_factory=list, max_length=8)


class ScoutAgent(BaseAgent):
    """Agent discovering external web sources and reusable internal knowledge via query portfolios."""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        search_connector: WebSearchConnector | None = None,
    ) -> None:
        super().__init__(role="scout", name="ScoutAgent", gateway=gateway)
        self.search_connector = search_connector or WebSearchConnector()
        self.portfolio_planner = QueryPortfolioPlanner()
        self.source_quality = SourceQuality()

    async def execute(
        self,
        subquestion: str,
        plan: Plan | None = None,
        already_seen: set[str] | list[str] | None = None,
        session: AsyncSession | None = None,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> ScoutOutput:
        """Scout external web sources and local knowledge base for relevant candidates."""
        seen_set = set(already_seen or [])
        candidates: list[SourceCandidate] = []
        settings = get_settings()

        # 1. Search existing internal knowledge base via FTS5
        if session:
            try:
                fts_chunks = await ClaimRepo.search_chunks_fts(session, subquestion[:40])
                for chunk in fts_chunks[:3]:
                    loc = f"internal://chunk/{chunk.id}"
                    if loc not in seen_set:
                        seen_set.add(loc)
                        candidates.append(
                            SourceCandidate(
                                location=loc,
                                title=f"Internal Knowledge: {chunk.text[:60]}...",
                                reason="Relevant existing knowledge in local corpus",
                                expected_relevance=0.85,
                            )
                        )
            except Exception as e:
                logger.debug(f"Internal knowledge FTS lookup skipped: {e}")

        # 2. Generate multi-angle query portfolio (direct, primary, counterevidence)
        queries = self.portfolio_planner.build(plan_item_id=subquestion[:24], question=subquestion)
        query_terms = set(self.portfolio_planner.keywords(subquestion))

        for q in queries[:3]:  # Execute top 3 prioritized portfolio queries
            search_results = await self.search_connector.fetch(q.text, max_results=6)
            for res in search_results:
                loc = res.url.strip()
                if not loc or loc in seen_set:
                    continue

                # Check connector domain security policy
                parsed = urllib.parse.urlparse(loc)
                domain = parsed.hostname or ""
                if domain and not default_policy_guard(domain, settings):
                    logger.debug(f"Scout filtering out policy-blocked domain '{domain}'")
                    continue

                seen_set.add(loc)
                q_score = self.source_quality.score(
                    url=loc,
                    title=res.title or domain,
                    snippet=res.snippet or "",
                    query_terms=query_terms,
                )

                candidates.append(
                    SourceCandidate(
                        location=loc,
                        title=res.title or domain,
                        reason=f"[{q.source_angle}] {res.snippet[:100] if res.snippet else 'Web search match'}",
                        snippet=res.snippet if res.snippet else None,
                        expected_relevance=q_score.total,
                    )
                )

        # 3. Sort by computed quality score and cap at 8 candidates
        candidates.sort(key=lambda c: c.expected_relevance, reverse=True)
        return ScoutOutput(candidates=candidates[:8])
