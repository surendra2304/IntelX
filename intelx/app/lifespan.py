"""Application lifespan management for startup, demonstration seeding, and background worker loop."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text

from intelx.core.logging import setup_logging
from intelx.core.settings import get_settings
from intelx.db.base import Base
from intelx.db.engine import dispose_engine, get_async_engine

logger = logging.getLogger("intelx.lifespan")


class EmbeddedWorkerHook:
    """Active background worker hook running OrchestrationWorker in an asyncio task."""

    def __init__(self) -> None:
        self.worker: Any = None
        self.task: asyncio.Task | None = None
        self.is_running = False

    async def start(self) -> None:
        """Start the background worker."""
        if self.is_running:
            return
        from intelx.orchestration.worker import OrchestrationWorker

        self.worker = OrchestrationWorker(poll_interval_s=1.0)
        self.task = asyncio.create_task(self.worker.start())
        self.is_running = True
        logger.info("Embedded background OrchestrationWorker started.")

    async def stop(self) -> None:
        """Stop the background worker."""
        if not self.is_running:
            return
        self.is_running = False
        if self.worker:
            self.worker.stop()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("Embedded background OrchestrationWorker stopped cleanly.")


worker_hook = EmbeddedWorkerHook()


class NewsIngesterHook:
    """Hook managing the continuous news ingestion background loop."""

    def __init__(self) -> None:
        from intelx.ingestion.news_ingester import NewsIngester
        self._ingester = NewsIngester(interval_seconds=300)

    async def start(self) -> None:
        await self._ingester.start()

    async def stop(self) -> None:
        await self._ingester.stop()


news_hook = NewsIngesterHook()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup, database initialization, and shutdown lifecycle."""
    settings = get_settings()

    # 1. Setup structured logging
    setup_logging(level="INFO")
    logger.info(f"Booting INTELX in [{settings.ENV}] mode (MOCK_MODE={settings.MOCK_MODE})")

    # 2. Ensure data directories exist
    data_dir = Path("./data").resolve()
    (data_dir / "raw").mkdir(parents=True, exist_ok=True)
    (data_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    # 3. Initialize database connection, schemas, and FTS5 search indexes
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "sqlite":
            await conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, text);"))
            await conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(id UNINDEXED, text, quote);"))
            await conn.execute(text(
                "CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks BEGIN "
                "INSERT INTO chunks_fts(id, text) VALUES (new.id, new.text); "
                "END;"
            ))
            await conn.execute(text(
                "CREATE TRIGGER IF NOT EXISTS chunks_after_delete AFTER DELETE ON chunks BEGIN "
                "DELETE FROM chunks_fts WHERE id = old.id; "
                "END;"
            ))
            await conn.execute(text(
                "CREATE TRIGGER IF NOT EXISTS claims_after_insert AFTER INSERT ON claims BEGIN "
                "INSERT INTO claims_fts(id, text, quote) VALUES (new.id, new.text, new.quote); "
                "END;"
            ))
            await conn.execute(text(
                "CREATE TRIGGER IF NOT EXISTS claims_after_delete AFTER DELETE ON claims BEGIN "
                "DELETE FROM claims_fts WHERE id = old.id; "
                "END;"
            ))
    logger.info("Database schemas and FTS5 indexes initialized.")

    # 3.5 Seed API keys from settings
    from intelx.core.auth import seed_api_keys_from_settings
    from intelx.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await seed_api_keys_from_settings(session, settings)
    logger.info("API keys seeded from settings.")

    # 3.6 Seed demonstration research runs if empty
    from intelx.db.demo_seeder import auto_seed_demonstrations_if_empty

    async with sessionmaker() as session:
        await auto_seed_demonstrations_if_empty(session)

    # 4. Start background worker hook
    await worker_hook.start()

    # 5. Start continuous news ingestion
    await news_hook.start()
    logger.info("Continuous news ingestion started.")

    yield

    # Shutdown sequence
    logger.info("Initiating INTELX shutdown sequence...")
    await news_hook.stop()
    await worker_hook.stop()
    await dispose_engine()
    logger.info("INTELX shutdown complete.")
