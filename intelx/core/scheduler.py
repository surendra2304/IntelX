"""INTELX Resilient Execution Scheduler, Retry Safety, and Cancellation Handling."""

from __future__ import annotations

import asyncio
import inspect
import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configurable exponential backoff retry policy with jitter."""

    attempts: int = 2
    base_delay: float = 0.25
    max_delay: float = 5.0
    jitter: bool = True
    timeout_seconds: float | None = None
    retryable_errors: tuple[str, ...] = (
        "timeout",
        "429",
        "502",
        "503",
        "504",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "rate limit",
    )

    def __post_init__(self) -> None:
        """Reject invalid retry budgets and timings before task execution."""
        if (
            isinstance(self.attempts, bool)
            or not isinstance(self.attempts, int)
            or self.attempts < 0
        ):
            raise ValueError("attempts must be a non-negative integer")
        for name, value in (
            ("base_delay", self.base_delay),
            ("max_delay", self.max_delay),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.timeout_seconds is not None and (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a finite positive number or None")
        if not isinstance(self.retryable_errors, tuple) or any(
            not isinstance(error, str) or not error.strip() for error in self.retryable_errors
        ):
            raise ValueError("retryable_errors must be a tuple of non-empty strings")


def retryable(exc: Exception, policy: RetryPolicy = RetryPolicy()) -> bool:
    """Classify transient failures by type first, then configured message markers."""
    if isinstance(exc, asyncio.CancelledError):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    message = f"{type(exc).__name__} {exc}".casefold()
    return any(target.casefold() in message for target in policy.retryable_errors)


async def bounded_call(
    fn: Callable[[], Any],
    policy: RetryPolicy = RetryPolicy(),
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> Any:
    """Execute async function with exponential backoff and jitter, failing fast on non-retryable errors."""

    async def invoke() -> Any:
        result = fn()
        if not inspect.isawaitable(result):
            raise TypeError("scheduled callable must return an awaitable")
        return await result

    for i in range(policy.attempts + 1):
        try:
            if policy.timeout_seconds is not None:
                return await asyncio.wait_for(invoke(), timeout=policy.timeout_seconds)
            return await invoke()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if i >= policy.attempts or not retryable(exc, policy):
                raise
            raw_delay = min(policy.max_delay, policy.base_delay * (2**i))
            delay = random.uniform(raw_delay * 0.5, raw_delay * 1.5) if policy.jitter else raw_delay
            if on_retry:
                on_retry(i + 1, exc, delay)
            await asyncio.sleep(delay)


class ExecutionScheduler:
    """Manages concurrent execution limits, bulk task coordination, and cancellation boundaries."""

    def __init__(self, max_concurrency: int = 5) -> None:
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency < 1
        ):
            raise ValueError("max_concurrency must be a positive integer")
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def run(
        self,
        coro_fn: Callable[[], Any],
        policy: RetryPolicy = RetryPolicy(),
    ) -> Any:
        """Run an async function within the concurrency semaphore and with retry safety."""
        async with self.semaphore:
            return await bounded_call(coro_fn, policy=policy)

    async def gather_bounded(
        self,
        tasks: list[Callable[[], Any]],
        policy: RetryPolicy = RetryPolicy(),
        return_exceptions: bool = False,
    ) -> list[Any]:
        """Execute a list of task callables concurrently bounded by the semaphore."""
        coroutines = [self.run(t, policy=policy) for t in tasks]
        return await asyncio.gather(*coroutines, return_exceptions=return_exceptions)


__all__ = [
    "RetryPolicy",
    "retryable",
    "bounded_call",
    "ExecutionScheduler",
]
