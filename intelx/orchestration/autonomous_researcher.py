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

from intelx.core.enums import RunStatus
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

    def __init__(
        self,
        interval_seconds: float = RESEARCH_CHECK_INTERVAL_SECONDS,
        initial_delay_seconds: float = 15.0,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.initial_delay_seconds = initial_delay_seconds
        self._task: asyncio.Task | None = None
        self._running = False
        self._topic_index = 0
        self._total_spawns = 0
        self._last_run_id: str | None = None
        self._last_spawn_time: datetime | None = None
        self._last_error: str | None = None

    @property
    def is_running(self) -> bool:
        """Check whether the autonomous research daemon is currently running."""
        return self._running

    @property
    def total_spawns(self) -> int:
        """Return cumulative count of autonomously spawned research runs."""
        return self._total_spawns

    @property
    def last_run_id(self) -> str | None:
        """Return the run ID of the most recently spawned autonomous run."""
        return self._last_run_id

    @property
    def last_spawn_time(self) -> datetime | None:
        """Return the UTC timestamp of the most recent autonomous run spawn."""
        return self._last_spawn_time

    @property
    def last_error(self) -> str | None:
        """Return the most recent error message encountered during a cycle."""
        return self._last_error

    async def _should_spawn_run(self, session: Any) -> bool:
        """Check if we have capacity and need a new autonomous run."""
        # Check active runs
        stmt_active = select(func.count(ResearchRun.id)).where(
            ResearchRun.status.in_(
                [
                    RunStatus.QUEUED,
                    RunStatus.PLANNING,
                    RunStatus.DISCOVERING,
                    RunStatus.RETRIEVING,
                    RunStatus.EXTRACTING,
                    RunStatus.VERIFYING,
                    RunStatus.ANALYZING,
                    RunStatus.SYNTHESIZING,
                ]
            )
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
            try:
                should_spawn = await self._should_spawn_run(session)
                if not should_spawn:
                    return None

                # Pick next rotating FRIDAY Universe topic
                topic = AUTONOMOUS_RESEARCH_TOPICS[
                    self._topic_index % len(AUTONOMOUS_RESEARCH_TOPICS)
                ]
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

                self._total_spawns += 1
                self._last_run_id = run.id
                self._last_spawn_time = datetime.now(UTC)
                self._last_error = None

                logger.info(
                    f"[AutoResearcher] Spawned autonomous investigation for [{topic['agent'].upper()}]: "
                    f"'{topic['objective'][:60]}...' (Run ID: {run.id})"
                )
                return run
            except Exception as e:
                self._last_error = str(e)
                raise

    async def trigger_for_agent(
        self,
        agent_name: str,
        objective: str | None = None,
        domain: str = "general",
        session_factory: Any | None = None,
    ) -> ResearchRun:
        """Trigger an autonomous investigation targeted for a specific specialist agent."""
        clean_agent = agent_name.lower().strip()
        default_objectives = {
            item["agent"]: item["objective"] for item in AUTONOMOUS_RESEARCH_TOPICS
        }
        target_objective = objective or default_objectives.get(
            clean_agent, f"Targeted autonomous research investigation for {clean_agent.upper()}"
        )

        factory = session_factory or get_sessionmaker()
        async with factory() as session:
            scope = {
                "domain": domain,
                "depth": "quick",
                "autonomous": True,
                "agent": clean_agent,
                "target_agent": clean_agent.upper(),
            }
            run = await RunRepo.create_run(
                session=session,
                objective=target_objective,
                scope_json=scope,
            )
            await session.commit()

            self._total_spawns += 1
            self._last_run_id = run.id
            self._last_spawn_time = datetime.now(UTC)

            logger.info(
                f"[AutoResearcher] Dispatched targeted run {run.id} for agent [{clean_agent.upper()}]: "
                f"'{target_objective[:60]}...'"
            )
            return run

    async def _loop(self) -> None:
        logger.info(
            f"[AutoResearcher] Started autonomous research engine "
            f"(checking every {self.interval_seconds}s)."
        )
        # Small initial delay on boot to let schemas and news ingester seed
        if self.initial_delay_seconds > 0:
            await asyncio.sleep(self.initial_delay_seconds)

        while self._running:
            try:
                await self.trigger_cycle()
            except Exception as ex:
                self._last_error = str(ex)
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
