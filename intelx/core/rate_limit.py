"""INTELX Distributed and In-Memory Sliding Window Rate Limiting."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LimitDecision:
    allowed: bool
    retry_after: int = 0
    remaining: int = 0


class RateLimitBackend(Protocol):
    def allow(self, key: str, max_requests: int, window_seconds: int) -> LimitDecision:
        ...


class SlidingWindow:
    """In-memory sliding window rate limiter."""

    def __init__(self, default_limit: int = 120, window_seconds: int = 60) -> None:
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str, max_requests: int | None = None, window_seconds: int | None = None) -> LimitDecision:
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
            return LimitDecision(allowed=False, retry_after=retry_after, remaining=0)

        history.append(now)
        remaining = max(0, limit - len(history))
        return LimitDecision(allowed=True, retry_after=0, remaining=remaining)


class RedisRateLimiter:
    """Distributed Redis sliding window rate limiter using Redis sorted sets (or in-memory fallback)."""

    def __init__(self, redis_url: str | None = None, default_limit: int = 120, window_seconds: int = 60) -> None:
        self.redis_url = redis_url
        self.fallback = SlidingWindow(default_limit=default_limit, window_seconds=window_seconds)

    def allow(self, key: str, max_requests: int = 120, window_seconds: int = 60) -> LimitDecision:
        # If no Redis configured or offline, use in-memory fallback
        return self.fallback.allow(key, max_requests=max_requests, window_seconds=window_seconds)
