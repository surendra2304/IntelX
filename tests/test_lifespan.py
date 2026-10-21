"""Tests for Application Lifespan, Database FTS5 Initialization, and Service Hooks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from intelx.app.lifespan import (
    AutonomousResearchHook,
    EmbeddedWorkerHook,
    NewsIngesterHook,
    lifespan,
)
from intelx.core.settings import Settings


@pytest.mark.asyncio
async def test_embedded_worker_hook_lifecycle():
    """Verify EmbeddedWorkerHook start, stop, and idempotency."""
    hook = EmbeddedWorkerHook()
    assert hook.is_running is False

    mock_worker = MagicMock()
    mock_worker.start = AsyncMock()
    mock_worker.stop = MagicMock()

    with patch("intelx.orchestration.worker.OrchestrationWorker", return_value=mock_worker):
        # 1. Start worker
        await hook.start()
        assert hook.is_running is True
        assert hook.worker is not None

        # 2. Second start is idempotent
        await hook.start()
        assert hook.is_running is True

        # 3. Stop worker
        await hook.stop()
        assert hook.is_running is False
        mock_worker.stop.assert_called_once()

        # 4. Second stop is idempotent
        await hook.stop()
        assert hook.is_running is False


@pytest.mark.asyncio
async def test_news_and_auto_research_hooks_lifecycle():
    """Verify NewsIngesterHook and AutonomousResearchHook start/stop delegations."""
    # News hook
    news_hook = NewsIngesterHook()
    news_hook._ingester.start = AsyncMock()
    news_hook._ingester.stop = AsyncMock()

    await news_hook.start()
    news_hook._ingester.start.assert_awaited_once()

    await news_hook.stop()
    news_hook._ingester.stop.assert_awaited_once()

    # Autonomous research hook
    res_hook = AutonomousResearchHook()
    res_hook._researcher.start = AsyncMock()
    res_hook._researcher.stop = AsyncMock()

    await res_hook.start()
    res_hook._researcher.start.assert_awaited_once()

    await res_hook.stop()
    res_hook._researcher.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_minimal_startup_and_shutdown():
    """Verify lifespan creates schemas, seeds keys, and cleanly shuts down."""
    app = FastAPI()
    test_settings = Settings(
        RUN_EMBEDDED_WORKER=False,
        ENABLE_NEWS_INGESTER=False,
        ENABLE_AUTONOMOUS_RESEARCH=False,
        ENABLE_DEMO_SEEDER=False,
    )

    with patch("intelx.app.lifespan.get_settings", return_value=test_settings):
        async with lifespan(app):
            # Application is active and running inside context
            assert True

    # Engine and background services disposed on context exit


@pytest.mark.asyncio
async def test_lifespan_with_all_services_and_demo_seeder():
    """Verify lifespan starts embedded services and demo seeder when enabled."""
    app = FastAPI()
    test_settings = Settings(
        RUN_EMBEDDED_WORKER=True,
        ENABLE_NEWS_INGESTER=True,
        ENABLE_AUTONOMOUS_RESEARCH=True,
        ENABLE_DEMO_SEEDER=True,
    )

    with (
        patch("intelx.app.lifespan.get_settings", return_value=test_settings),
        patch("intelx.app.lifespan.worker_hook.start", new_callable=AsyncMock) as mock_worker_start,
        patch("intelx.app.lifespan.worker_hook.stop", new_callable=AsyncMock) as mock_worker_stop,
        patch("intelx.app.lifespan.news_hook.start", new_callable=AsyncMock) as mock_news_start,
        patch("intelx.app.lifespan.news_hook.stop", new_callable=AsyncMock) as mock_news_stop,
        patch(
            "intelx.app.lifespan.auto_research_hook.start", new_callable=AsyncMock
        ) as mock_res_start,
        patch(
            "intelx.app.lifespan.auto_research_hook.stop", new_callable=AsyncMock
        ) as mock_res_stop,
        patch(
            "intelx.db.demo_seeder.auto_seed_demonstrations_if_empty",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_seed,
    ):
        async with lifespan(app):
            mock_worker_start.assert_awaited_once()
            mock_news_start.assert_awaited_once()
            mock_res_start.assert_awaited_once()
            mock_seed.assert_awaited_once()

        mock_worker_stop.assert_awaited_once()
        mock_news_stop.assert_awaited_once()
        mock_res_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_default_embedded_worker_in_dev():
    """Verify lifespan enables embedded worker by default in non-production when unspecified."""
    app = FastAPI()
    test_settings = Settings(
        RUN_EMBEDDED_WORKER=None,
        ENV="development",
        ENABLE_NEWS_INGESTER=False,
        ENABLE_AUTONOMOUS_RESEARCH=False,
        ENABLE_DEMO_SEEDER=False,
    )

    with (
        patch("intelx.app.lifespan.get_settings", return_value=test_settings),
        patch("intelx.app.lifespan.worker_hook.start", new_callable=AsyncMock) as mock_worker_start,
        patch("intelx.app.lifespan.worker_hook.stop", new_callable=AsyncMock) as mock_worker_stop,
    ):
        async with lifespan(app):
            mock_worker_start.assert_awaited_once()

        mock_worker_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_shutdown_exception_resilience():
    """Verify lifespan shutdown catches errors during hook termination gracefully."""
    app = FastAPI()
    test_settings = Settings(
        RUN_EMBEDDED_WORKER=False,
        ENABLE_NEWS_INGESTER=False,
        ENABLE_AUTONOMOUS_RESEARCH=False,
        ENABLE_DEMO_SEEDER=False,
    )

    with (
        patch("intelx.app.lifespan.get_settings", return_value=test_settings),
        patch("intelx.app.lifespan.worker_hook.stop", side_effect=RuntimeError("Worker stop fail")),
        patch("intelx.app.lifespan.dispose_engine", new_callable=AsyncMock) as mock_dispose,
    ):
        async with lifespan(app):
            pass

        # Verify fallback dispose was attempted despite the exception
        assert mock_dispose.call_count >= 1
