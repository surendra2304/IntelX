"""Application lifespan management for startup and graceful shutdown."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from intelx.core.logging import setup_logging
from intelx.core.settings import get_settings
from intelx.db.base import Base
from intelx.db.engine import dispose_engine, get_async_engine

logger = logging.getLogger("intelx.lifespan")


class NoOpWorkerHook:
    """No-op background worker hook for initial lifecycle staging."""

    def __init__(self) -> None:
        self.is_running = False

    async def start(self) -> None:
        """Start the background worker."""
        self.is_running = True
        logger.info("Background worker hook started (no-op mode).")

    async def stop(self) -> None:
        """Stop the background worker."""
        self.is_running = False
        logger.info("Background worker hook stopped.")


worker_hook = NoOpWorkerHook()


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

    # 3. Initialize database connection and schemas
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schemas initialized.")

    # 3.5 Seed API keys from settings
    from intelx.core.auth import seed_api_keys_from_settings
    from intelx.db.session import get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await seed_api_keys_from_settings(session, settings)
    logger.info("API keys seeded from settings.")

    # 4. Start background worker hook
    await worker_hook.start()

    yield

    # Shutdown sequence
    logger.info("Initiating INTELX shutdown sequence...")
    await worker_hook.stop()
    await dispose_engine()
    logger.info("INTELX shutdown complete.")
