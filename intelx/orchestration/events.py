"""INTELX Orchestration Event Stream, Broadcaster, and Real-Time Telemetry."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import RunOutcome, RunStatus
from intelx.db.models import Event
from intelx.db.repos import RunRepo

logger = logging.getLogger(__name__)


class EventStreamManager:
    """In-memory publish/subscribe event hub for live SSE research streams."""

    _subscribers: dict[str, list[asyncio.Queue[Event | dict[str, Any]]]] = defaultdict(list)

    @classmethod
    def subscribe(cls, run_id: str) -> asyncio.Queue[Event | dict[str, Any]]:
        """Subscribe to real-time events for a specific research run."""
        queue: asyncio.Queue[Event | dict[str, Any]] = asyncio.Queue()
        cls._subscribers[run_id].append(queue)
        return queue

    @classmethod
    def unsubscribe(cls, run_id: str, queue: asyncio.Queue[Event | dict[str, Any]]) -> None:
        """Unsubscribe and remove an event queue."""
        if run_id in cls._subscribers and queue in cls._subscribers[run_id]:
            cls._subscribers[run_id].remove(queue)
            if not cls._subscribers[run_id]:
                del cls._subscribers[run_id]

    @classmethod
    async def broadcast(cls, run_id: str, event: Event | dict[str, Any]) -> None:
        """Broadcast an event to all active subscribers of a research run."""
        if run_id in cls._subscribers:
            for queue in list(cls._subscribers[run_id]):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    @classmethod
    async def iterate_events(
        cls, run_id: str, timeout: float = 30.0
    ) -> AsyncIterator[dict[str, Any]]:
        """Async generator yielding live events formatted for SSE streams."""
        queue = cls.subscribe(run_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                    if isinstance(event, Event):
                        yield {
                            "id": event.id,
                            "run_id": event.run_id,
                            "type": event.type,
                            "payload": event.payload_json,
                            "created_at": (
                                event.created_at.isoformat() if event.created_at else None
                            ),
                        }
                    else:
                        yield event
                except TimeoutError:
                    yield {"type": "ping", "run_id": run_id}
        finally:
            cls.unsubscribe(run_id, queue)


async def emit_event(
    session: AsyncSession,
    run_id: str,
    event_type: str,
    payload_json: dict[str, Any] | None = None,
) -> Event:
    """Persist an event to the database and broadcast it to live subscribers."""
    event = await RunRepo.add_event(
        session=session,
        run_id=run_id,
        event_type=event_type,
        payload_json=payload_json or {},
    )
    await EventStreamManager.broadcast(run_id, event)
    return event


async def emit_stage_changed(
    session: AsyncSession,
    run_id: str,
    old_stage: RunStatus | str,
    new_stage: RunStatus | str,
) -> Event:
    """Emit a stage transition event."""
    return await emit_event(
        session=session,
        run_id=run_id,
        event_type="stage.changed",
        payload_json={
            "old_stage": str(old_stage),
            "new_stage": str(new_stage),
        },
    )


async def emit_budget_warning(
    session: AsyncSession,
    run_id: str,
    percent_used: float,
    spent_usd: float,
    max_usd: float,
) -> Event:
    """Emit a budget warning event when threshold (80%) is crossed."""
    return await emit_event(
        session=session,
        run_id=run_id,
        event_type="budget.warning",
        payload_json={
            "percent_used": round(percent_used, 2),
            "spent_usd": round(spent_usd, 4),
            "max_usd": round(max_usd, 4),
        },
    )


async def emit_review_required(
    session: AsyncSession,
    run_id: str,
    reason: str,
    disputed_claim_ids: list[str] | None = None,
) -> Event:
    """Emit a human review required pause event."""
    return await emit_event(
        session=session,
        run_id=run_id,
        event_type="review.required",
        payload_json={
            "reason": reason,
            "disputed_claim_ids": disputed_claim_ids or [],
        },
    )


async def emit_research_completed(
    session: AsyncSession,
    run_id: str,
    outcome: RunOutcome | str,
    cost_summary: dict[str, Any] | None = None,
) -> Event:
    """Emit final research completion telemetry."""
    return await emit_event(
        session=session,
        run_id=run_id,
        event_type="research.completed",
        payload_json={
            "outcome": str(outcome),
            "cost_summary": cost_summary or {},
        },
    )
