"""Tests for bounded sliding-window and token-bucket rate limiters."""

import time

import pytest

from intelx.core.rate_limit import (
    LimitDecision,
    RateLimitBackendUnavailable,
    RedisRateLimiter,
    SlidingWindow,
    TokenBucketLimiter,
)


def test_sliding_window_allow_and_limit():
    limiter = SlidingWindow(default_limit=3, window_seconds=2)
    assert limiter.allow("ip-1") == LimitDecision(
        allowed=True, remaining=2, limit=3, window_seconds=2
    )
    assert limiter.allow("ip-1").remaining == 1
    assert limiter.allow("ip-1").remaining == 0
    denied = limiter.allow("ip-1")
    assert not denied.allowed
    assert denied.remaining == 0
    assert denied.retry_after >= 1
    assert limiter.allow("ip-2").allowed
    assert limiter.get_usage("ip-1") == 3

    limiter.reset("ip-1")
    assert limiter.get_usage("ip-1") == 0
    assert limiter.allow("ip-1").allowed


def test_sliding_window_cleanup():
    limiter = SlidingWindow(default_limit=5, window_seconds=1)
    limiter.allow("user-a")
    limiter.allow("user-b")
    time.sleep(1.05)
    assert limiter.cleanup() == 2
    assert len(limiter._history) == 0


def test_sliding_window_caps_key_history_and_evicts_lru():
    limiter = SlidingWindow(default_limit=5, window_seconds=10, max_tracked_keys=2)
    limiter.allow("key-a")
    limiter.allow("key-b")
    limiter.allow("key-a")
    assert list(limiter._history) == ["key-b", "key-a"]

    limiter.allow("key-c")
    assert list(limiter._history) == ["key-a", "key-c"]
    assert len(limiter._history) == 2


@pytest.mark.parametrize(
    ("limit", "window"),
    [(0, 10), (1, 0), (-1, 2)],
)
def test_sliding_window_rejects_invalid_defaults(limit, window):
    with pytest.raises(ValueError):
        SlidingWindow(default_limit=limit, window_seconds=window)


def test_sliding_window_rejects_invalid_overrides_and_keys():
    limiter = SlidingWindow()
    with pytest.raises(ValueError, match="max_requests"):
        limiter.allow("key", max_requests=0)
    with pytest.raises(ValueError, match="window_seconds"):
        limiter.allow("key", window_seconds=-1)
    with pytest.raises(ValueError, match="non-empty"):
        limiter.allow(" ")


def test_token_bucket_limiter_refills_and_resets():
    bucket = TokenBucketLimiter(rate_per_second=10.0, capacity=5.0)
    assert bucket.allow("client-1", tokens=5.0).allowed
    assert not bucket.allow("client-1", tokens=1.0).allowed
    time.sleep(0.2)
    assert bucket.allow("client-1", tokens=1.0).allowed
    bucket.reset()
    assert len(bucket._buckets) == 0


def test_token_bucket_caps_keys_and_rejects_impossible_requests():
    bucket = TokenBucketLimiter(rate_per_second=1.0, capacity=5.0, max_tracked_keys=2)
    bucket.allow("key-a")
    bucket.allow("key-b")
    bucket.allow("key-a")
    bucket.allow("key-c")
    assert list(bucket._buckets) == ["key-a", "key-c"]
    assert len(bucket._buckets) == 2

    with pytest.raises(ValueError, match="no greater than capacity"):
        bucket.allow("key-a", tokens=6.0)
    with pytest.raises(ValueError):
        TokenBucketLimiter(rate_per_second=0.0)
    with pytest.raises(ValueError):
        TokenBucketLimiter(capacity=float("inf"))


class FakeRedis:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else [1, 0, 4, 1]
        self.error = error
        self.calls = []

    def eval(self, script, numkeys, key, now_ms, window_ms, limit, member):
        self.calls.append((script, numkeys, key, now_ms, window_ms, limit, member))
        if self.error:
            raise self.error
        return self.result

    def zremrangebyscore(self, *args):
        return 0

    def zcard(self, *args):
        return 2

    def delete(self, *args):
        return len(args)

    def scan_iter(self, **kwargs):
        return iter([])


def test_redis_rate_limiter_uses_atomic_script_when_configured():
    client = FakeRedis(result=[1, 0, 4, 1])
    limiter = RedisRateLimiter(
        "redis://example.test:6379/0",
        default_limit=5,
        window_seconds=30,
        redis_client=client,
    )

    decision = limiter.allow("sensitive-client-identifier")
    assert decision == LimitDecision(allowed=True, remaining=4, limit=5, window_seconds=30)
    assert len(client.calls) == 1
    script, numkeys, redis_key, _now_ms, window_ms, limit, member = client.calls[0]
    assert "ZREMRANGEBYSCORE" in script
    assert "ZADD" in script
    assert "PEXPIRE" in script
    assert numkeys == 1
    assert redis_key.startswith(RedisRateLimiter._KEY_PREFIX)
    assert "sensitive-client-identifier" not in redis_key
    assert window_ms == 30_000
    assert limit == 5
    assert member


def test_redis_rate_limiter_does_not_fallback_when_configured_backend_fails():
    client = FakeRedis(error=OSError("connection refused"))
    limiter = RedisRateLimiter(
        "redis://example.test:6379/0",
        redis_client=client,
        default_limit=2,
        window_seconds=10,
    )
    with pytest.raises(RateLimitBackendUnavailable, match="request rejected"):
        limiter.allow("client")
    assert len(limiter.fallback._history) == 0


def test_redis_rate_limiter_uses_bounded_fallback_when_unconfigured():
    limiter = RedisRateLimiter(redis_url=None, default_limit=2, window_seconds=2)
    assert limiter.allow("test-key").allowed
    assert limiter.allow("test-key").allowed
    assert not limiter.allow("test-key").allowed
    limiter.reset("test-key")
    assert limiter.fallback.get_usage("test-key") == 0
