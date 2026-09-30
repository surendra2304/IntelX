"""Await ecosystem deliveries and retain truthful per-recipient outcomes."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any


async def dispatch_sequentially(
    deliveries: Sequence[tuple[str, Callable[[], Awaitable[Any]]]],
    *,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Run delivery attempts in order and report every outcome.

    These sends share an idempotent Memora event ID, so they must not race one
    another. Each attempt is awaited before the next starts; a failure is
    recorded and does not hide later recipient failures or prevent attempts.
    """
    outcomes: dict[str, Any] = {}
    for recipient, deliver in deliveries:
        try:
            result = await deliver()
            outcomes[recipient] = result
            status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
            if status in {"stored", "stored_mock", "accepted", "delivered", "delivered_mock"}:
                logger.info("IntelX ecosystem delivery %s: %s", recipient, status)
            else:
                logger.warning("IntelX ecosystem delivery %s: %s", recipient, status)
        except Exception as exc:
            outcomes[recipient] = {"status": "error", "error": type(exc).__name__}
            logger.warning(
                "IntelX ecosystem delivery %s raised %s",
                recipient,
                type(exc).__name__,
                exc_info=True,
            )
    return outcomes
