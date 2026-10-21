"""Bounded in-memory and atomic Redis-backed rate-limiting primitives."""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger("intelx.rate_limit")


@dataclass(frozen=True, slots=True)
class LimitDecision:
    """Outcome of a rate-limit evaluation."""

    allowed: bool
    retry_after: int = 0
    remaining: int = 0
    limit: int = 0
    window_seconds: int = 0


class RateLimitBackendUnavailable(RuntimeError):
    """Raised when a configured rate-limit backend cannot be reached safely."""


class RateLimitBackend(Protocol):
    """Protocol shared by in-memory and distributed rate limiters."""

    def allow(
        self, key: str, max_requests: int | None = None, window_seconds: int | None = None
    ) -> LimitDecision: ...


def _positive_int(value: int, name: str) -> int:
    """Validate a positive integer without accepting booleans or lossy coercions."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _key(value: str) -> str:
    """Validate a caller key before it is retained in memory or sent to Redis."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("rate-limit key must be a non-empty string")
    return value


class SlidingWindow:
    """Thread-safe, bounded sliding-window log limiter with least-recently-used eviction."""

    def __init__(
        self,
        default_limit: int = 120,
        window_seconds: int = 60,
        max_tracked_keys: int = 10_000,
    ) -> None:
        self.default_limit = _positive_int(default_limit, "default_limit")
        self.window_seconds = _positive_int(window_seconds, "window_seconds")
        self.max_tracked_keys = _positive_int(max_tracked_keys, "max_tracked_keys")
        self._history: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.RLock()

    def allow(
        self, key: str, max_requests: int | None = None, window_seconds: int | None = None
    ) -> LimitDecision:
        """Consume one unit or return a retry delay; invalid overrides fail explicitly."""
        key = _key(key)
        limit = (
            self.default_limit
            if max_requests is None
            else _positive_int(max_requests, "max_requests")
        )
        window = (
            self.window_seconds
            if window_seconds is None
            else _positive_int(window_seconds, "window_seconds")
        )
        now = time.monotonic()
        cutoff = now - window

        with self._lock:
            history = [ts for ts in self._history.get(key, ()) if ts > cutoff]
            if history:
                self._history[key] = history
                self._history.move_to_end(key)
            else:
                self._history.pop(key, None)

            if len(history) >= limit:
                retry_after = max(1, math.ceil(window - (now - history[0])))
                return LimitDecision(
                    allowed=False,
                    retry_after=retry_after,
                    remaining=0,
                    limit=limit,
                    window_seconds=window,
                )

            if key not in self._history and len(self._history) >= self.max_tracked_keys:
                self._history.popitem(last=False)

            history.append(now)
            self._history[key] = history
            self._history.move_to_end(key)
            return LimitDecision(
                allowed=True,
                remaining=max(0, limit - len(history)),
                limit=limit,
                window_seconds=window,
            )

    def get_usage(self, key: str, window_seconds: int | None = None) -> int:
        """Count requests for a key in the selected rolling window."""
        key = _key(key)
        window = (
            self.window_seconds
            if window_seconds is None
            else _positive_int(window_seconds, "window_seconds")
        )
        cutoff = time.monotonic() - window
        with self._lock:
            history = [ts for ts in self._history.get(key, ()) if ts > cutoff]
            if history:
                self._history[key] = history
                self._history.move_to_end(key)
            else:
                self._history.pop(key, None)
            return len(history)

    def reset(self, key: str | None = None) -> None:
        """Clear one key or all local history."""
        with self._lock:
            if key is None:
                self._history.clear()
            else:
                self._history.pop(_key(key), None)

    def cleanup(self) -> int:
        """Remove idle keys and return the number evicted."""
        cutoff = time.monotonic() - self.window_seconds
        with self._lock:
            expired = [
                key
                for key, timestamps in self._history.items()
                if not timestamps or timestamps[-1] <= cutoff
            ]
            for key in expired:
                del self._history[key]
            return len(expired)


class TokenBucketLimiter:
    """Thread-safe token-bucket limiter with bounded state and monotonic-time refill."""

    def __init__(
        self,
        rate_per_second: float = 10.0,
        capacity: float = 20.0,
        max_tracked_keys: int = 10_000,
    ) -> None:
        if not math.isfinite(rate_per_second) or rate_per_second <= 0:
            raise ValueError("rate_per_second must be a finite positive number")
        if not math.isfinite(capacity) or capacity <= 0:
            raise ValueError("capacity must be a finite positive number")
        self.rate_per_second = rate_per_second
        self.capacity = capacity
        self.max_tracked_keys = _positive_int(max_tracked_keys, "max_tracked_keys")
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.RLock()

    def allow(self, key: str, tokens: float = 1.0) -> LimitDecision:
        """Consume tokens or return the rounded-up seconds required to refill."""
        key = _key(key)
        if not math.isfinite(tokens) or tokens <= 0 or tokens > self.capacity:
            raise ValueError("tokens must be finite, positive, and no greater than capacity")

        now = time.monotonic()
        with self._lock:
            current, last_refill = self._buckets.get(key, (self.capacity, now))
            refilled = min(
                self.capacity, current + max(0.0, now - last_refill) * self.rate_per_second
            )
            if refilled >= tokens:
                remaining = refilled - tokens
                if key not in self._buckets and len(self._buckets) >= self.max_tracked_keys:
                    self._buckets.popitem(last=False)
                self._buckets[key] = (remaining, now)
                self._buckets.move_to_end(key)
                return LimitDecision(
                    allowed=True,
                    remaining=int(remaining),
                    limit=math.floor(self.capacity),
                    window_seconds=1,
                )

            # Requests larger than the bucket capacity are rejected above, so refill
            # can always eventually satisfy every valid request.
            retry_after = max(1, math.ceil((tokens - refilled) / self.rate_per_second))
            self._buckets[key] = (refilled, now)
            self._buckets.move_to_end(key)
            return LimitDecision(
                allowed=False,
                retry_after=retry_after,
                remaining=0,
                limit=math.floor(self.capacity),
                window_seconds=1,
            )

    def reset(self, key: str | None = None) -> None:
        """Clear one bucket or all bucket state."""
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(_key(key), None)


_REDIS_WINDOW_SCRIPT = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local request_limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count >= request_limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 1
    if oldest[2] then
        retry_after = math.max(1, math.ceil((tonumber(oldest[2]) + window_ms - now_ms) / 1000))
    end
    return {0, retry_after, 0, count}
end

redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
count = count + 1
return {1, 0, math.max(0, request_limit - count), count}
"""


class RedisRateLimiter:
    """Atomic Redis sliding-window limiter; local fallback is used only when unconfigured.

    Redis is optional. Install the `redis` extra and supply a URL to enable shared
    enforcement across workers. A configured-but-unavailable Redis backend raises
    `RateLimitBackendUnavailable` rather than silently weakening the limit.
    """

    _KEY_PREFIX = "intelx:rate-limit:"

    def __init__(
        self,
        redis_url: str | None = None,
        default_limit: int = 120,
        window_seconds: int = 60,
        *,
        redis_client: Any | None = None,
        max_tracked_keys: int = 10_000,
    ) -> None:
        self.default_limit = _positive_int(default_limit, "default_limit")
        self.window_seconds = _positive_int(window_seconds, "window_seconds")
        self.redis_url = (
            redis_url.strip() if isinstance(redis_url, str) and redis_url.strip() else None
        )
        self.fallback = SlidingWindow(
            default_limit=self.default_limit,
            window_seconds=self.window_seconds,
            max_tracked_keys=max_tracked_keys,
        )
        self._redis = redis_client
        if self.redis_url and self._redis is None:
            try:
                import redis
            except ImportError as exc:
                raise RuntimeError(
                    "Redis URL configured but the optional dependency is missing; install intelx[redis]."
                ) from exc
            self._redis = redis.Redis.from_url(
                self.redis_url,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
                health_check_interval=30,
                decode_responses=False,
            )

    def allow(
        self, key: str, max_requests: int | None = None, window_seconds: int | None = None
    ) -> LimitDecision:
        """Evaluate atomically in Redis when configured, otherwise use bounded local state."""
        key = _key(key)
        limit = (
            self.default_limit
            if max_requests is None
            else _positive_int(max_requests, "max_requests")
        )
        window = (
            self.window_seconds
            if window_seconds is None
            else _positive_int(window_seconds, "window_seconds")
        )
        if self._redis is None:
            return self.fallback.allow(key, max_requests=limit, window_seconds=window)

        now_ms = int(time.time() * 1000)
        redis_key = self._redis_key(key)
        member = f"{now_ms}:{uuid.uuid4().hex}"
        try:
            raw = self._redis.eval(
                _REDIS_WINDOW_SCRIPT,
                1,
                redis_key,
                now_ms,
                window * 1000,
                limit,
                member,
            )
            allowed, retry_after, remaining, _count = (int(value) for value in raw)
        except Exception as exc:
            logger.error("Configured Redis rate limiter failed (%s)", type(exc).__name__)
            raise RateLimitBackendUnavailable(
                "Redis rate-limit backend is unavailable; request rejected to avoid bypassing limits"
            ) from exc

        return LimitDecision(
            allowed=bool(allowed),
            retry_after=max(0, retry_after),
            remaining=max(0, remaining),
            limit=limit,
            window_seconds=window,
        )

    def get_usage(self, key: str, window_seconds: int | None = None) -> int:
        """Return active usage for local fallback; Redis usage must be obtained atomically in Lua."""
        if self._redis is None:
            return self.fallback.get_usage(key, window_seconds)
        key = _key(key)
        window = (
            self.window_seconds
            if window_seconds is None
            else _positive_int(window_seconds, "window_seconds")
        )
        try:
            now_ms = int(time.time() * 1000)
            redis_key = self._redis_key(key)
            self._redis.zremrangebyscore(redis_key, "-inf", now_ms - window * 1000)
            return int(self._redis.zcard(redis_key))
        except Exception as exc:
            logger.error("Redis rate-limit usage query failed (%s)", type(exc).__name__)
            raise RateLimitBackendUnavailable("Redis rate-limit backend is unavailable") from exc

    def reset(self, key: str | None = None) -> None:
        """Reset one key or clear the entire namespaced Redis set."""
        if self._redis is None:
            self.fallback.reset(key)
            return
        try:
            if key is not None:
                self._redis.delete(self._redis_key(_key(key)))
                return
            pending: list[str] = []
            for redis_key in self._redis.scan_iter(match=f"{self._KEY_PREFIX}*", count=500):
                pending.append(redis_key)
                if len(pending) >= 500:
                    self._redis.delete(*pending)
                    pending.clear()
            if pending:
                self._redis.delete(*pending)
        except Exception as exc:
            logger.error("Redis rate-limit reset failed (%s)", type(exc).__name__)
            raise RateLimitBackendUnavailable("Redis rate-limit backend is unavailable") from exc

    def _redis_key(self, key: str) -> str:
        """Avoid storing raw client keys or identifiers in Redis key names."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"{self._KEY_PREFIX}{digest}"


__all__ = [
    "LimitDecision",
    "RateLimitBackend",
    "RateLimitBackendUnavailable",
    "SlidingWindow",
    "TokenBucketLimiter",
    "RedisRateLimiter",
]
