"""INTELX Background Task Worker Loop and Execution Daemon."""

import asyncio
import logging
import signal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import RunOutcome, RunStatus
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
        self._processed_count = 0
        self._failure_count = 0
        self._active_job_id: str | None = None
        self._active_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Check if worker polling loop is running."""
        return self._running

    @property
    def processed_count(self) -> int:
        """Total number of successfully completed research jobs."""
        return self._processed_count

    @property
    def failure_count(self) -> int:
        """Total number of jobs that failed during execution."""
        return self._failure_count

    @property
    def active_job_id(self) -> str | None:
        """The run ID currently being processed, or None if idle."""
        return self._active_job_id

    async def claim_next_job(self, session: AsyncSession) -> ResearchRun | None:
        """Atomically claim the highest-priority eligible queued run."""
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
        self._active_job_id = run_id

        # 2. Execute job in a separate transaction
        async with self._active_lock:
            async with factory() as session:
                try:
                    await self.engine.execute_run(session=session, run_id=run_id)
                    await session.commit()
                    self._processed_count += 1
                    logger.info(f"Worker completed research run {run_id}")
                except Exception as e:
                    self._failure_count += 1
                    logger.exception(f"Worker caught error processing run {run_id}: {e}")
                    await session.rollback()

                    # Mark as FAILED
                    try:
                        await RunRepo.set_status(
                            session=session,
                            run_id=run_id,
                            status=RunStatus.FAILED,
                            outcome=RunOutcome.FAILED,
                            error_json={"error": str(e), "type": type(e).__name__},
                        )
                        await session.commit()
                    except Exception as inner_e:
                        logger.error(
                            f"Failed to update run status to FAILED for {run_id}: {inner_e}"
                        )
                finally:
                    self._active_job_id = None

        return True

    async def run_batch(self, limit: int = 10, session_factory: Any | None = None) -> int:
        """Execute queued jobs sequentially up to limit or until queue is empty."""
        processed_total = 0
        for _ in range(limit):
            processed = await self.run_once(session_factory=session_factory)
            if not processed:
                break
            processed_total += 1
        return processed_total

    async def drain(self, timeout_seconds: float = 5.0) -> bool:
        """Stop accepting new jobs and wait for the currently executing job to finish."""
        self.stop()
        if self._active_job_id is None:
            return True
        try:
            async with asyncio.timeout(timeout_seconds):
                while self._active_job_id is not None:
                    await asyncio.sleep(0.1)
            return True
        except TimeoutError:
            logger.warning(f"Worker drain timed out with active job: {self._active_job_id}")
            return False

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
