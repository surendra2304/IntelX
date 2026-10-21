"""Tests for Execution Scheduler, Retries, and Circuit Breakers."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from intelx.connectors.providers import (
    CircuitState,
    ProviderHealth,
    ProviderRouter,
)
from intelx.core.scheduler import ExecutionScheduler, RetryPolicy, bounded_call


@pytest.mark.asyncio
async def test_bounded_call_retry_success():
    """Verify bounded_call retries transient errors and succeeds on subsequent attempt."""
    attempts = 0
    retry_log = []

    async def flaky_work():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("HTTP 429 rate limit exceeded")
        return "success"

    def record_retry(attempt, exc, delay):
        retry_log.append((attempt, str(exc), delay))

    policy = RetryPolicy(attempts=3, base_delay=0.01, max_delay=0.05, jitter=False)
    result = await bounded_call(flaky_work, policy=policy, on_retry=record_retry)

    assert result == "success"
    assert attempts == 3
    assert len(retry_log) == 2


@pytest.mark.asyncio
async def test_bounded_call_non_retryable_fails_fast():
    """Non-retryable exceptions immediately bubble up without retrying."""
    attempts = 0

    async def invalid_work():
        nonlocal attempts
        attempts += 1
        raise ValueError("Invalid schema formatting")

    policy = RetryPolicy(attempts=3, base_delay=0.01)
    with pytest.raises(ValueError, match="Invalid schema"):
        await bounded_call(invalid_work, policy=policy)

    assert attempts == 1


@pytest.mark.asyncio
async def test_execution_scheduler_concurrency_bounding():
    """Verify ExecutionScheduler limits concurrent workers with its semaphore."""
    scheduler = ExecutionScheduler(max_concurrency=2)
    active_now = 0
    max_active_observed = 0

    async def mock_task():
        nonlocal active_now, max_active_observed
        active_now += 1
        max_active_observed = max(max_active_observed, active_now)
        await asyncio.sleep(0.02)
        active_now -= 1
        return "done"

    tasks = [mock_task for _ in range(6)]
    results = await scheduler.gather_bounded(tasks)

    assert len(results) == 6
    assert all(r == "done" for r in results)
    assert max_active_observed <= 2


def test_provider_circuit_breaker_lifecycle():
    """Verify CLOSED -> OPEN -> HALF_OPEN -> CLOSED state machine transitions."""
    health = ProviderHealth(
        name="tavily", failure_threshold=2, success_threshold=2, cooldown_seconds=0.05
    )

    assert health.state == CircuitState.CLOSED
    assert health.is_healthy() is True

    # 1st failure: still closed
    health.record_failure("timeout")
    assert health.consecutive_failures == 1
    assert health.state == CircuitState.CLOSED
    assert health.is_healthy() is True

    # 2nd failure: trips to OPEN
    health.record_failure("HTTP 503")
    assert health.consecutive_failures == 2
    assert health.state == CircuitState.OPEN
    assert health.available is False

    # Immediate check: still OPEN
    assert health.is_healthy() is False

    # Wait for cooldown
    import time

    time.sleep(0.06)

    # First check after cooldown transitions to HALF_OPEN (canary mode)
    assert health.is_healthy() is True
    assert health.state == CircuitState.HALF_OPEN

    # 1st canary success
    health.record_success()
    assert health.state == CircuitState.HALF_OPEN

    # 2nd canary success: fully recovers to CLOSED
    health.record_success()
    assert health.state == CircuitState.CLOSED
    assert health.available is True
    assert health.consecutive_failures == 0


@pytest.mark.asyncio
async def test_provider_router_fallback():
    """Verify ProviderRouter routes to secondary provider when primary fails."""
    primary = AsyncMock()
    primary.name = "primary"
    primary_health = ProviderHealth(name="primary")
    primary.health = lambda: primary_health
    primary.generate.side_effect = RuntimeError("Primary API down")

    secondary = AsyncMock()
    secondary.name = "secondary"
    secondary_health = ProviderHealth(name="secondary")
    secondary.health = lambda: secondary_health
    secondary.generate.return_value = {"answer": "grounded_response"}

    router = ProviderRouter([primary, secondary])
    result = await router.call("extractor", {"prompt": "extract entities"})

    assert result == {"answer": "grounded_response"}
    assert primary.generate.call_count == 1
    assert secondary.generate.call_count == 1
    assert primary_health.consecutive_failures == 1
    assert secondary_health.total_calls == 1
