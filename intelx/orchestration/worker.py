"""INTELX Background Task Worker Loop and Execution Daemon."""

import asyncio
import logging
import signal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import RunStatus
from intelx.core.logging import setup_logging
from intelx.db.models import ResearchRun
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker
from intelx.orchestration.engine import OrchestrationEngine

logger = logging.getLogger(__name__)


class OrchestrationWorker:
    """Async background worker claiming and executing queued research runs."""

    def __init__(
        self,
        engine: OrchestrationEngine | None = None,
        poll_interval_s: float = 1.0,
    ) -> None:
        self.engine = engine or OrchestrationEngine()
        self.poll_interval_s = poll_interval_s
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def claim_next_job(self, session: AsyncSession) -> ResearchRun | None:
        """Atomically claim the oldest QUEUED run in the database."""
        # Find next QUEUED run
        stmt = (
            select(ResearchRun)
            .where(ResearchRun.status == RunStatus.QUEUED)
            .order_by(ResearchRun.created_at.asc())
            .limit(1)
        )
        res = await session.execute(stmt)
        run = res.scalar_one_or_none()
        if not run:
            return None

        # Lock and claim atomically
        return await RunRepo.claim_next_queued_run(session)

    async def run_once(self, session_factory: Any | None = None) -> bool:
        """Attempt to claim and execute a single research job."""
        factory = session_factory or get_sessionmaker()
        
        # 1. Claim job in its own transaction
        async with factory() as session:
            run = await self.claim_next_job(session)
            if not run:
                return False
            await session.commit()
            run_id = run.id
            objective = run.objective

        logger.info(f"Worker claimed research run {run_id} ('{objective[:40]}...')")
        
        # 2. Execute job in a separate transaction
        async with factory() as session:
            try:
                await self.engine.execute_run(session=session, run_id=run_id)
                await session.commit()
                logger.info(f"Worker completed research run {run_id}")
            except Exception as e:
                logger.exception(f"Worker caught error processing run {run_id}: {e}")
                await session.rollback()
                
                # Mark as FAILED
                try:
                    from intelx.core.enums import RunOutcome
                    await RunRepo.set_status(
                        session=session,
                        run_id=run_id,
                        status=RunStatus.FAILED,
                        outcome=RunOutcome.FAILED,
                        error_json={"error": str(e), "type": type(e).__name__}
                    )
                    await session.commit()
                except Exception as inner_e:
                    logger.error(f"Failed to update run status to FAILED for {run_id}: {inner_e}")
                    
            return True

    async def start(self) -> None:
        """Run the persistent polling loop until cancelled."""
        self._running = True
        self._shutdown_event.clear()
        factory = get_sessionmaker()
        logger.info("INTELX Orchestration Worker started.")

        while self._running:
            try:
                processed = await self.run_once(factory)
                if not processed:
                    await asyncio.sleep(self.poll_interval_s)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Unexpected worker loop iteration error: {e}")
                await asyncio.sleep(self.poll_interval_s)

        logger.info("INTELX Orchestration Worker stopped.")

    def stop(self) -> None:
        """Signal the worker loop to terminate gracefully."""
        self._running = False
        self._shutdown_event.set()


async def main() -> None:
    """CLI entrypoint for running worker standalone."""
    setup_logging()
    worker = OrchestrationWorker()

    def _handle_signal(*args: Any) -> None:
        logger.info("Shutdown signal received.")
        worker.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, AttributeError):
            pass

    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
