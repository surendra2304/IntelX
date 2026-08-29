"""INTELX Scout Agent: Web and Internal Knowledge Discovery."""

import logging
import urllib.parse
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.base import BaseAgent
from intelx.agents.planner import Plan
from intelx.connectors.base import default_policy_guard
from intelx.connectors.search import WebSearchConnector
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
    """Agent discovering external web sources and reusable internal knowledge."""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        search_connector: WebSearchConnector | None = None,
    ) -> None:
        super().__init__(role="scout", name="ScoutAgent", gateway=gateway)
        self.search_connector = search_connector or WebSearchConnector()

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

        # 2. External Web Search
        search_query = f"{subquestion} {plan.objective}" if plan and plan.objective else subquestion
        search_results = await self.search_connector.fetch(search_query, max_results=8)
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
            candidates.append(
                SourceCandidate(
                    location=loc,
                    title=res.title or domain,
                    reason=res.snippet[:120] if res.snippet else "Web search match",
                    snippet=res.snippet if res.snippet else None,
                    expected_relevance=0.90,
                )
            )

        # 3. Sort by relevance and cap at 8 candidates
        candidates.sort(key=lambda c: c.expected_relevance, reverse=True)
        return ScoutOutput(candidates=candidates[:8])
