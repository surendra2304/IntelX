"""Comprehensive unit and integration tests for the AutonomousResearcher daemon."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from intelx.core.enums import RunStatus
from intelx.db.models import ResearchRun
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker
from intelx.orchestration.autonomous_researcher import (
    AUTONOMOUS_RESEARCH_TOPICS,
    AutonomousResearcher,
)


@pytest.mark.asyncio
async def test_autonomous_researcher_initial_state():
    """Verify default properties and telemetry counters on daemon creation."""
    daemon = AutonomousResearcher(interval_seconds=10.0, initial_delay_seconds=0.0)
    assert not daemon.is_running
    assert daemon.total_spawns == 0
    assert daemon.last_run_id is None
    assert daemon.last_spawn_time is None
    assert daemon.last_error is None
    assert daemon.interval_seconds == 10.0
    assert daemon.initial_delay_seconds == 0.0


@pytest.mark.asyncio
async def test_should_spawn_run_capacity_and_rate_limits():
    """Verify capacity checking against active and recent runs."""
    daemon = AutonomousResearcher()
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        # Initially in a clean test DB with no active runs -> should spawn
        should_spawn = await daemon._should_spawn_run(session)
        assert should_spawn is True

        # Create 2 active runs to fill MAX_CONCURRENT_AUTONOMOUS_RUNS
        run1 = await RunRepo.create_run(session, objective="Active Run 1")
        run1.status = RunStatus.RETRIEVING
        run2 = await RunRepo.create_run(session, objective="Active Run 2")
        run2.status = RunStatus.ANALYZING
        await session.commit()

        # Capacity should now be saturated
        assert await daemon._should_spawn_run(session) is False

        # Mark them completed
        run1.status = RunStatus.COMPLETED
        run2.status = RunStatus.COMPLETED
        await session.commit()

        # Both runs were created within the last hour -> recent count >= 2 -> should still be False
        assert await daemon._should_spawn_run(session) is False

        # Simulate older runs beyond 1 hour
        run1.created_at = datetime.now(UTC) - timedelta(hours=2)
        run2.created_at = datetime.now(UTC) - timedelta(hours=2)
        await session.commit()

        # Now capacity should open up again
        assert await daemon._should_spawn_run(session) is True


@pytest.mark.asyncio
async def test_trigger_cycle_rotates_topics_and_updates_telemetry():
    """Verify topic rotation and run creation across FRIDAY Universe agents."""
    daemon = AutonomousResearcher(initial_delay_seconds=0.0)
    sessionmaker = get_sessionmaker()

    # Clear recent runs by completing them if any exist
    async with sessionmaker() as session:
        runs = (await session.execute(ResearchRun.__table__.select())).fetchall()
        for r in runs:
            await RunRepo.set_status(session, r.id, status=RunStatus.COMPLETED)
        await session.commit()

    # Trigger cycle 1: Stratex
    run1 = await daemon.trigger_cycle(sessionmaker)
    assert run1 is not None
    assert daemon.total_spawns == 1
    assert daemon.last_run_id == run1.id
    assert daemon.last_spawn_time is not None
    assert daemon.last_error is None
    assert run1.scope_json["agent"] == AUTONOMOUS_RESEARCH_TOPICS[0]["agent"]
    assert run1.scope_json["autonomous"] is True

    # Trigger cycle 2: Sentinel (recent_count is 1 < 2, so this succeeds)
    run2 = await daemon.trigger_cycle(sessionmaker)
    assert run2 is not None
    assert daemon.total_spawns == 2
    assert daemon.last_run_id == run2.id
    assert run2.scope_json["agent"] == AUTONOMOUS_RESEARCH_TOPICS[1]["agent"]

    # Trigger cycle 3: Should be rejected because recent_count >= 2 in the past hour
    run_rejected = await daemon.trigger_cycle(sessionmaker)
    assert run_rejected is None
    assert daemon.total_spawns == 2

    # Age runs to allow next cycle
    async with sessionmaker() as session:
        for r_id in (run1.id, run2.id):
            db_run = await RunRepo.get_run(session, r_id)
            if db_run:
                db_run.created_at = datetime.now(UTC) - timedelta(hours=2)
                db_run.status = RunStatus.COMPLETED
        await session.commit()

    # Trigger cycle 3: Friday (now succeeds after aging past runs)
    run3 = await daemon.trigger_cycle(sessionmaker)
    assert run3 is not None
    assert daemon.total_spawns == 3
    assert daemon.last_run_id == run3.id
    assert run3.scope_json["agent"] == AUTONOMOUS_RESEARCH_TOPICS[2]["agent"]


@pytest.mark.asyncio
async def test_trigger_for_agent_targeted_dispatch():
    """Verify targeted autonomous research spawning for specific agent identities."""
    daemon = AutonomousResearcher()
    sessionmaker = get_sessionmaker()

    # 1. Stratex with default objective
    run_stratex = await daemon.trigger_for_agent("stratex", session_factory=sessionmaker)
    assert run_stratex.scope_json["agent"] == "stratex"
    assert run_stratex.scope_json["target_agent"] == "STRATEX"
    assert (
        "cryptocurrency" in run_stratex.objective.lower()
        or "binance" in run_stratex.objective.lower()
    )

    # 2. Sentinel with custom objective and domain
    custom_obj = "Analyze zero-day exploit targeting linux kernel ebpf subsystems"
    run_sentinel = await daemon.trigger_for_agent(
        "sentinel", objective=custom_obj, domain="security", session_factory=sessionmaker
    )
    assert run_sentinel.scope_json["agent"] == "sentinel"
    assert run_sentinel.scope_json["domain"] == "security"
    assert run_sentinel.objective == custom_obj

    # 3. Arbitrary agent identity with fallback objective
    run_custom = await daemon.trigger_for_agent("cortex", session_factory=sessionmaker)
    assert run_custom.scope_json["agent"] == "cortex"
    assert "CORTEX" in run_custom.objective


@pytest.mark.asyncio
async def test_autonomous_researcher_lifecycle_start_stop():
    """Verify start, idempotent start, and graceful stop."""
    daemon = AutonomousResearcher(interval_seconds=0.1, initial_delay_seconds=0.0)
    assert not daemon.is_running

    await daemon.start()
    assert daemon.is_running

    # Idempotent start: calling again shouldn't create a new task
    first_task = daemon._task
    await daemon.start()
    assert daemon._task is first_task

    # Allow loop to tick briefly
    await asyncio.sleep(0.05)

    await daemon.stop()
    assert not daemon.is_running
    assert daemon._task.cancelled() or daemon._task.done()

    # Calling stop again is safe
    await daemon.stop()
