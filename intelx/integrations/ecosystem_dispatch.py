"""Await ecosystem deliveries and retain truthful per-recipient outcomes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any


# Total time the whole dispatch may consume. Each recipient already carries its own
# retry budget, and awaiting them one after another multiplied that budget by the
# recipient count: with an unreachable peer, a research request stalled ~90s and
# then failed, even though the research itself had already succeeded. One overall
# deadline makes the caller-facing latency independent of how many peers are down.
TOTAL_BUDGET_SECONDS = 15.0


async def dispatch_sequentially(
    deliveries: Sequence[tuple[str, Callable[[], Awaitable[Any]]]],
    *,
    logger: logging.Logger,
    budget_seconds: float = TOTAL_BUDGET_SECONDS,
) -> dict[str, Any]:
    """Run delivery attempts in order and report every outcome.

    These sends share an idempotent Memora event ID, so they must not race one
    another. Each attempt is awaited before the next starts; a failure is
    recorded and does not hide later recipient failures or prevent attempts.

    The whole sequence shares one deadline. Recipients still waiting when it
    expires are reported as skipped rather than left to consume the caller's
    patience, so an unreachable peer degrades the delivery instead of the request.
    """
    outcomes: dict[str, Any] = {}

    async def run_all() -> None:
        for recipient, deliver in deliveries:
            try:
                result = await deliver()
                outcomes[recipient] = result
                status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
                if status in {"stored", "stored_mock", "accepted", "delivered", "delivered_mock"}:
                    logger.info("IntelX ecosystem delivery %s: %s", recipient, status)
                else:
                    logger.warning("IntelX ecosystem delivery %s: %s", recipient, status)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                outcomes[recipient] = {"status": "error", "error": type(exc).__name__}
                logger.warning(
                    "IntelX ecosystem delivery %s raised %s",
                    recipient,
                    type(exc).__name__,
                    exc_info=True,
                )

    try:
        await asyncio.wait_for(run_all(), timeout=budget_seconds)
    except asyncio.TimeoutError:
        pending = [name for name, _ in deliveries if name not in outcomes]
        logger.warning(
            "IntelX ecosystem dispatch budget of %ss expired; %d recipient(s) undelivered: %s",
            budget_seconds, len(pending), ", ".join(pending) or "none",
        )
        for recipient in pending:
            outcomes[recipient] = {"status": "skipped", "error": "dispatch_budget_exhausted"}
    return outcomes
