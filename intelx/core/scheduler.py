"""INTELX Resilient Execution Scheduler, Retry Safety, and Cancellation Handling."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configurable exponential backoff retry policy."""

    attempts: int = 2
    base_delay: float = 0.25
    max_delay: float = 5.0
    retryable_errors: tuple[str, ...] = ("timeout", "429", "503", "connection reset", "temporarily unavailable")


def retryable(exc: Exception, policy: RetryPolicy = RetryPolicy()) -> bool:
    """Classify whether an exception is transient and safe to retry."""
    if isinstance(exc, asyncio.CancelledError):
        return False
    msg = str(exc).lower()
    return any(target in msg for target in policy.retryable_errors)


async def bounded_call(
    fn: Callable[[], Any],
    policy: RetryPolicy = RetryPolicy(),
) -> Any:
    """Execute async function with exponential backoff, failing fast on non-retryable errors."""
    for i in range(policy.attempts + 1):
        try:
            return await fn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if i >= policy.attempts or not retryable(exc, policy):
                raise
            delay = min(policy.max_delay, policy.base_delay * (2**i))
            await asyncio.sleep(delay)
