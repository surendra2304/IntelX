"""INTELX — Autonomous Research Daemon for the FRIDAY Universe.

Continuously and autonomously creates and dispatches real research investigations
for the FRIDAY Universe agents:

  - Stratex: Crypto market volatility & Binance algorithmic catalysts
  - Sentinel: Cybersecurity threats, zero-days, CVEs, defense posture
  - FRIDAY: Mobile hardware announcements, product launches, AI models
  - Futuris: Macroeconomic indicators, inflation data, predictive regimes

Runs in an asyncio background loop alongside the OrchestrationWorker and NewsIngester.
Ensures IntelX is actively researching 24/7 without requiring manual user input.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from intelx.core.enums import RunOutcome, RunStatus
from intelx.db.models import ResearchRun
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker

logger = logging.getLogger("intelx.autonomous_researcher")

# Continuous research objectives tailored to FRIDAY Universe agents
AUTONOMOUS_RESEARCH_TOPICS = [
    {
        "agent": "stratex",
        "domain": "market",
        "objective": "Investigate recent cryptocurrency market volatility, regulatory signals, and Binance algorithmic trade catalysts",
    },
    {
        "agent": "sentinel",
        "domain": "security",
        "objective": "Analyze emerging zero-day exploits, CVE vulnerability advisories, and proactive cybersecurity defense mitigations",
    },
    {
        "agent": "friday",
        "domain": "general",
        "objective": "Assess announced mobile hardware, product release schedules, and consumer tech deployments for FRIDAY OS",
    },
    {
        "agent": "futuris",
        "domain": "market",
        "objective": "Evaluate global macroeconomic indicators, central bank rate forecasts, and predictive market indices",
    },
]

RESEARCH_CHECK_INTERVAL_SECONDS = 900  # Check every 15 minutes
MAX_CONCURRENT_AUTONOMOUS_RUNS = 2


class AutonomousResearcher:
    """Daemon automatically spawning continuous research runs for FRIDAY Universe agents."""

    def __init__(self, interval_seconds: float = RESEARCH_CHECK_INTERVAL_SECONDS) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False
        self._topic_index = 0

    async def _should_spawn_run(self, session: Any) -> bool:
        """Check if we have capacity and need a new autonomous run."""
        # Check active runs
        stmt_active = select(func.count(ResearchRun.id)).where(
            ResearchRun.status.in_([RunStatus.QUEUED, RunStatus.PLANNING, RunStatus.DISCOVERING,
                                   RunStatus.RETRIEVING, RunStatus.EXTRACTING, RunStatus.VERIFYING,
                                   RunStatus.ANALYZING, RunStatus.SYNTHESIZING])
        )
        active_count = (await session.execute(stmt_active)).scalar() or 0
        if active_count >= MAX_CONCURRENT_AUTONOMOUS_RUNS:
            logger.debug(f"[AutoResearcher] {active_count} runs already active. Skipping spawn.")
            return False

        # Check runs created in last 1 hour
        one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
        stmt_recent = select(func.count(ResearchRun.id)).where(
            ResearchRun.created_at >= one_hour_ago
        )
        recent_count = (await session.execute(stmt_recent)).scalar() or 0
        # If fewer than 2 runs in the past hour, we should spawn
        return recent_count < 2

    async def trigger_cycle(self, session_factory: Any | None = None) -> ResearchRun | None:
        """Evaluate intelligence state and trigger an autonomous research investigation."""
        factory = session_factory or get_sessionmaker()
        async with factory() as session:
            should_spawn = await self._should_spawn_run(session)
            if not should_spawn:
                return None

            # Pick next rotating FRIDAY Universe topic
            topic = AUTONOMOUS_RESEARCH_TOPICS[self._topic_index % len(AUTONOMOUS_RESEARCH_TOPICS)]
            self._topic_index += 1

            scope = {
                "domain": topic["domain"],
                "depth": "quick",
                "autonomous": True,
                "agent": topic["agent"],
                "target_agent": topic["agent"].upper(),
            }

            run = await RunRepo.create_run(
                session=session,
                objective=topic["objective"],
                scope_json=scope,
            )
            await session.commit()
            logger.info(
                f"[AutoResearcher] Spawned autonomous investigation for [{topic['agent'].upper()}]: "
                f"'{topic['objective'][:60]}...' (Run ID: {run.id})"
            )
            return run

    async def _loop(self) -> None:
        logger.info(
            f"[AutoResearcher] Started autonomous research engine "
            f"(checking every {self.interval_seconds}s)."
        )
        # Small initial delay on boot to let schemas and news ingester seed
        await asyncio.sleep(15.0)

        while self._running:
            try:
                await self.trigger_cycle()
            except Exception as ex:
                logger.error(f"[AutoResearcher] Error in autonomous cycle: {ex}", exc_info=True)

            if self._running:
                await asyncio.sleep(self.interval_seconds)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[AutoResearcher] Background loop started.")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("[AutoResearcher] Stopped.")
