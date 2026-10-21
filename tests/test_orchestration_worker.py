"""Comprehensive unit and integration tests for OrchestrationWorker."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from intelx.core.enums import RunOutcome, RunStatus
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker
from intelx.orchestration.worker import OrchestrationWorker


@pytest.mark.asyncio
async def test_worker_initial_properties():
    """Verify worker initialization defaults and telemetry counters."""
    worker = OrchestrationWorker(poll_interval_s=0.05)
    assert not worker.is_running
    assert worker.processed_count == 0
    assert worker.failure_count == 0
    assert worker.active_job_id is None
    assert worker.poll_interval_s == 0.05


@pytest.mark.asyncio
async def test_worker_run_once_when_queue_empty():
    """Worker returns False immediately when no queued jobs exist."""
    worker = OrchestrationWorker()
    sessionmaker = get_sessionmaker()

    # In an empty or caught-up queue
    result = await worker.run_once(session_factory=sessionmaker)
    assert result is False
    assert worker.processed_count == 0
    assert worker.failure_count == 0
    assert worker.active_job_id is None


@pytest.mark.asyncio
async def test_worker_claims_and_executes_run_successfully():
    """Worker claims next queued run and executes it to completion via engine."""
    mock_engine = AsyncMock()
    mock_engine.execute_run = AsyncMock(return_value=None)
    worker = OrchestrationWorker(engine=mock_engine)
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Orchestration worker test job",
            scope_json={"domain": "general"},
        )
        await session.commit()
        run_id = run.id

    # Execute one iteration
    executed = await worker.run_once(session_factory=sessionmaker)
    assert executed is True
    assert worker.processed_count == 1
    assert worker.failure_count == 0
    assert worker.active_job_id is None
    mock_engine.execute_run.assert_awaited_once()

    # Verify run status in database
    async with sessionmaker() as session:
        updated = await RunRepo.get_run(session, run_id)
        assert updated is not None


@pytest.mark.asyncio
async def test_worker_handles_execution_failure_gracefully():
    """Worker marks run FAILED with error payload when engine encounters an exception."""
    mock_engine = AsyncMock()
    mock_engine.execute_run = AsyncMock(side_effect=RuntimeError("Simulated LLM network timeout"))
    worker = OrchestrationWorker(engine=mock_engine)
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Worker failing job test",
        )
        await session.commit()
        run_id = run.id

    # Execute iteration
    executed = await worker.run_once(session_factory=sessionmaker)
    assert executed is True
    assert worker.processed_count == 0
    assert worker.failure_count == 1
    assert worker.active_job_id is None

    # Verify run was marked FAILED with error_json
    async with sessionmaker() as session:
        failed_run = await RunRepo.get_run(session, run_id)
        assert failed_run is not None
        assert failed_run.status == RunStatus.FAILED
        assert failed_run.outcome == RunOutcome.FAILED
        assert failed_run.error_json is not None
        assert "Simulated LLM network timeout" in failed_run.error_json.get("error", "")


@pytest.mark.asyncio
async def test_worker_run_batch_limit():
    """Verify run_batch processes multiple queued jobs sequentially up to limit."""
    mock_engine = AsyncMock()
    worker = OrchestrationWorker(engine=mock_engine)
    sessionmaker = get_sessionmaker()

    # Create 3 queued runs
    async with sessionmaker() as session:
        for i in range(3):
            await RunRepo.create_run(session, objective=f"Batch Run {i}")
        await session.commit()

    # Process with limit=2
    batch_count = await worker.run_batch(limit=2, session_factory=sessionmaker)
    assert batch_count == 2
    assert worker.processed_count == 2

    # Process remaining
    remaining = await worker.run_batch(limit=5, session_factory=sessionmaker)
    assert remaining == 1
    assert worker.processed_count == 3


@pytest.mark.asyncio
async def test_worker_drain_and_lifecycle():
    """Verify drain behavior and start/stop polling loop."""
    worker = OrchestrationWorker(poll_interval_s=0.02)

    # 1. Drain when idle -> returns True immediately
    drained = await worker.drain(timeout_seconds=0.5)
    assert drained is True
    assert not worker.is_running

    # 2. Start worker in background
    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.05)
    assert worker.is_running

    # 3. Stop worker
    worker.stop()
    await task
    assert not worker.is_running
