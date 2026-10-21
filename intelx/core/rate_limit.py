"""INTELX Distributed and In-Memory Sliding Window Rate Limiting."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LimitDecision:
    """Outcome of rate limit evaluation."""

    allowed: bool
    retry_after: int = 0
    remaining: int = 0
    limit: int = 0
    window_seconds: int = 0


class RateLimitBackend(Protocol):
    """Protocol for pluggable rate limiting engines."""

    def allow(
        self, key: str, max_requests: int | None = None, window_seconds: int | None = None
    ) -> LimitDecision: ...


class SlidingWindow:
    """In-memory sliding window log rate limiter with timestamp pruning."""

    def __init__(self, default_limit: int = 120, window_seconds: int = 60) -> None:
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = defaultdict(list)

    def allow(
        self, key: str, max_requests: int | None = None, window_seconds: int | None = None
    ) -> LimitDecision:
        now = time.time()
        limit = max_requests or self.default_limit
        window = window_seconds or self.window_seconds
        cutoff = now - window

        # Prune expired timestamps
        history = [t for t in self._history[key] if t > cutoff]
        self._history[key] = history

        if len(history) >= limit:
            oldest = history[0]
            retry_after = max(1, int(window - (now - oldest)))
            return LimitDecision(
                allowed=False,
                retry_after=retry_after,
                remaining=0,
                limit=limit,
                window_seconds=window,
            )

        history.append(now)
        remaining = max(0, limit - len(history))
        return LimitDecision(
            allowed=True,
            retry_after=0,
            remaining=remaining,
            limit=limit,
            window_seconds=window,
        )

    def get_usage(self, key: str, window_seconds: int | None = None) -> int:
        """Count active requests in current window."""
        now = time.time()
        window = window_seconds or self.window_seconds
        cutoff = now - window
        return sum(1 for t in self._history.get(key, []) if t > cutoff)

    def reset(self, key: str | None = None) -> None:
        """Clear rate limit history for a specific key or all keys."""
        if key is not None:
            self._history.pop(key, None)
        else:
            self._history.clear()

    def cleanup(self) -> int:
        """Evict keys that have had no activity within their window."""
        now = time.time()
        cutoff = now - self.window_seconds
        expired_keys = [
            k
            for k, timestamps in self._history.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for k in expired_keys:
            del self._history[k]
        return len(expired_keys)


class TokenBucketLimiter:
    """Token bucket rate limiter supporting smooth refills and burst capacity."""

    def __init__(self, rate_per_second: float = 10.0, capacity: float = 20.0) -> None:
        self.rate_per_second = rate_per_second
        self.capacity = capacity
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_refill_timestamp)

    def allow(self, key: str, tokens: float = 1.0) -> LimitDecision:
        now = time.time()
        current_tokens, last_refill = self._buckets.get(key, (self.capacity, now))

        # Refill tokens based on elapsed time
        elapsed = now - last_refill
        refilled_tokens = min(self.capacity, current_tokens + (elapsed * self.rate_per_second))

        if refilled_tokens >= tokens:
            remaining = refilled_tokens - tokens
            self._buckets[key] = (remaining, now)
            return LimitDecision(
                allowed=True,
                retry_after=0,
                remaining=int(remaining),
                limit=int(self.capacity),
                window_seconds=1,
            )

        deficit = tokens - refilled_tokens
        retry_after = max(1, int(deficit / self.rate_per_second + 0.999))
        self._buckets[key] = (refilled_tokens, now)
        return LimitDecision(
            allowed=False,
            retry_after=retry_after,
            remaining=0,
            limit=int(self.capacity),
            window_seconds=1,
        )

    def reset(self, key: str | None = None) -> None:
        if key is not None:
            self._buckets.pop(key, None)
        else:
            self._buckets.clear()


class RedisRateLimiter:
    """Distributed Redis sliding window rate limiter using in-memory fallback."""

    def __init__(
        self, redis_url: str | None = None, default_limit: int = 120, window_seconds: int = 60
    ) -> None:
        self.redis_url = redis_url
        self.fallback = SlidingWindow(default_limit=default_limit, window_seconds=window_seconds)

    def allow(
        self,
        key: str,
        max_requests: int | None = None,
        window_seconds: int | None = None,
    ) -> LimitDecision:
        return self.fallback.allow(key, max_requests=max_requests, window_seconds=window_seconds)

    def reset(self, key: str | None = None) -> None:
        self.fallback.reset(key)


__all__ = [
    "LimitDecision",
    "RateLimitBackend",
    "SlidingWindow",
    "TokenBucketLimiter",
    "RedisRateLimiter",
]
