"""Comprehensive unit and integration tests for Orchestration Events & Telemetry."""

import asyncio

import pytest

from intelx.core.enums import RunOutcome, RunStatus
from intelx.db.repos import RunRepo
from intelx.db.session import get_sessionmaker
from intelx.orchestration.events import (
    EventStreamManager,
    emit_budget_warning,
    emit_claim_extracted,
    emit_contradiction_flagged,
    emit_research_completed,
    emit_review_required,
    emit_source_ingested,
    emit_stage_changed,
)


@pytest.fixture(autouse=True)
def clean_subscribers():
    """Ensure clean subscriber state before and after each test."""
    EventStreamManager.clear_all_subscribers()
    yield
    EventStreamManager.clear_all_subscribers()


@pytest.mark.asyncio
async def test_event_stream_manager_subscription_lifecycle():
    """Verify subscribe, get_subscriber_count, unsubscribe, and clear."""
    run_id = "run-event-test-001"
    assert EventStreamManager.get_subscriber_count(run_id) == 0

    # Subscribe 2 queues
    q1 = EventStreamManager.subscribe(run_id)
    assert EventStreamManager.get_subscriber_count(run_id) == 1
    q2 = EventStreamManager.subscribe(run_id)
    assert EventStreamManager.get_subscriber_count(run_id) == 2

    # Unsubscribe 1
    EventStreamManager.unsubscribe(run_id, q1)
    assert EventStreamManager.get_subscriber_count(run_id) == 1

    # Unsubscribe second
    EventStreamManager.unsubscribe(run_id, q2)
    assert EventStreamManager.get_subscriber_count(run_id) == 0

    # Subscribe again and clear_all
    _ = EventStreamManager.subscribe(run_id)
    _ = EventStreamManager.subscribe("other-run")
    assert EventStreamManager.get_subscriber_count(run_id) == 1
    EventStreamManager.clear_all_subscribers()
    assert EventStreamManager.get_subscriber_count(run_id) == 0


@pytest.mark.asyncio
async def test_event_stream_manager_broadcast_and_queue_full():
    """Verify broadcast to subscribers and handling of full queues."""
    run_id = "run-broadcast-002"
    q_normal = EventStreamManager.subscribe(run_id)

    # Mock a full queue
    q_full = asyncio.Queue(maxsize=1)
    q_full.put_nowait({"type": "existing_message"})
    EventStreamManager._subscribers[run_id].append(q_full)

    # Broadcast event
    test_event = {"type": "test.broadcast", "message": "hello subscribers"}
    await EventStreamManager.broadcast(run_id, test_event)

    # Normal queue received it
    msg = q_normal.get_nowait()
    assert msg == test_event

    # Full queue dropped without error
    assert q_full.qsize() == 1


@pytest.mark.asyncio
async def test_event_stream_manager_iterate_events():
    """Verify async generator formatting and timeout ping behavior."""
    run_id = "run-iter-003"
    received_events = []

    async def consumer():
        async for item in EventStreamManager.iterate_events(run_id, timeout=0.05):
            received_events.append(item)
            if len(received_events) >= 2:
                break

    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0.01)

    # Broadcast raw dict
    await EventStreamManager.broadcast(run_id, {"type": "manual.ping", "data": 123})

    # Wait for timeout ping to occur
    await asyncio.wait_for(consumer_task, timeout=1.0)

    assert len(received_events) == 2
    assert received_events[0]["type"] == "manual.ping"
    assert received_events[1]["type"] == "ping"

    # Subscriber should have been cleaned up automatically on generator termination
    assert EventStreamManager.get_subscriber_count(run_id) == 0


@pytest.mark.asyncio
async def test_emit_stage_changed_and_budget_warning():
    """Verify DB persistence and broadcast of stage change and budget warning events."""
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        # Create base run
        run = await RunRepo.create_run(session, objective="Stage transition test")
        await session.commit()
        run_id = run.id

    sub_q = EventStreamManager.subscribe(run_id)

    async with sessionmaker() as session:
        # Emit stage changed
        ev_stage = await emit_stage_changed(
            session=session,
            run_id=run_id,
            old_stage=RunStatus.QUEUED,
            new_stage=RunStatus.PLANNING,
        )
        assert ev_stage.type == "stage.changed"
        assert ev_stage.payload_json["old_stage"] == str(RunStatus.QUEUED)
        assert ev_stage.payload_json["new_stage"] == str(RunStatus.PLANNING)

        # Emit budget warning
        ev_budget = await emit_budget_warning(
            session=session,
            run_id=run_id,
            percent_used=82.5,
            spent_usd=0.0825,
            max_usd=0.10,
        )
        assert ev_budget.type == "budget.warning"
        assert ev_budget.payload_json["percent_used"] == 82.5
        assert ev_budget.payload_json["spent_usd"] == 0.0825

        await session.commit()

    # Subscriber received both broadcast events
    assert sub_q.qsize() == 2
    b1 = sub_q.get_nowait()
    b2 = sub_q.get_nowait()
    assert b1.type == "stage.changed"
    assert b2.type == "budget.warning"


@pytest.mark.asyncio
async def test_emit_review_required_and_research_completed():
    """Verify review.required and research.completed event emission."""
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        run = await RunRepo.create_run(session, objective="Review required test")
        await session.commit()
        run_id = run.id

    sub_q = EventStreamManager.subscribe(run_id)

    async with sessionmaker() as session:
        # Review required
        ev_review = await emit_review_required(
            session=session,
            run_id=run_id,
            reason="High contradiction density detected",
            disputed_claim_ids=["claim-1", "claim-2"],
        )
        assert ev_review.type == "review.required"
        assert ev_review.payload_json["reason"] == "High contradiction density detected"
        assert ev_review.payload_json["disputed_claim_ids"] == ["claim-1", "claim-2"]

        # Research completed
        ev_comp = await emit_research_completed(
            session=session,
            run_id=run_id,
            outcome=RunOutcome.ANSWERED,
            cost_summary={"total_cost_usd": 0.012, "model_calls": 3},
        )
        assert ev_comp.type == "research.completed"
        assert ev_comp.payload_json["outcome"] == str(RunOutcome.ANSWERED)
        assert ev_comp.payload_json["cost_summary"]["total_cost_usd"] == 0.012

        await session.commit()

    assert sub_q.qsize() == 2


@pytest.mark.asyncio
async def test_emit_source_claim_and_contradiction_events():
    """Verify domain-specific telemetry event emitters."""
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        run = await RunRepo.create_run(session, objective="Domain telemetry test")
        await session.commit()
        run_id = run.id

    sub_q = EventStreamManager.subscribe(run_id)

    async with sessionmaker() as session:
        # 1. Source ingested
        ev_src = await emit_source_ingested(
            session=session,
            run_id=run_id,
            source_id="src-99",
            url="https://nature.com/articles/battery-2026",
            title="Battery Breakthrough 2026",
        )
        assert ev_src.type == "source.ingested"
        assert ev_src.payload_json["url"] == "https://nature.com/articles/battery-2026"

        # 2. Claim extracted
        ev_cl = await emit_claim_extracted(
            session=session,
            run_id=run_id,
            claim_id="cl-88",
            quote="Cathode delivers 220 Wh/kg",
            span_start=15,
            span_end=42,
        )
        assert ev_cl.type == "claim.extracted"
        assert ev_cl.payload_json["quote"] == "Cathode delivers 220 Wh/kg"

        # 3. Contradiction flagged
        ev_contra = await emit_contradiction_flagged(
            session=session,
            run_id=run_id,
            topic="Specific Energy",
            claim_a_id="cl-88",
            claim_b_id="cl-89",
        )
        assert ev_contra.type == "contradiction.flagged"
        assert ev_contra.payload_json["topic"] == "Specific Energy"

        await session.commit()

    assert sub_q.qsize() == 3
