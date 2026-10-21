"""Tests for Sliding Window and Token Bucket Rate Limiters."""

import time

from intelx.core.rate_limit import RedisRateLimiter, SlidingWindow, TokenBucketLimiter


def test_sliding_window_allow_and_limit():
    """Verify requests within limit are allowed and surplus requests return retry_after."""
    limiter = SlidingWindow(default_limit=3, window_seconds=2)

    # First 3 requests allowed
    d1 = limiter.allow("ip-1")
    assert d1.allowed is True
    assert d1.remaining == 2

    d2 = limiter.allow("ip-1")
    assert d2.allowed is True
    assert d2.remaining == 1

    d3 = limiter.allow("ip-1")
    assert d3.allowed is True
    assert d3.remaining == 0

    # 4th request rejected
    d4 = limiter.allow("ip-1")
    assert d4.allowed is False
    assert d4.remaining == 0
    assert d4.retry_after >= 1

    # Different key is independent
    d_other = limiter.allow("ip-2")
    assert d_other.allowed is True

    # Usage check
    assert limiter.get_usage("ip-1") == 3
    assert limiter.get_usage("ip-2") == 1

    # Reset
    limiter.reset("ip-1")
    assert limiter.get_usage("ip-1") == 0
    d_after_reset = limiter.allow("ip-1")
    assert d_after_reset.allowed is True


def test_sliding_window_cleanup():
    """Verify cleanup prunes inactive keys."""
    limiter = SlidingWindow(default_limit=5, window_seconds=1)
    limiter.allow("user-a")
    limiter.allow("user-b")

    time.sleep(1.05)
    evicted = limiter.cleanup()
    assert evicted == 2
    assert len(limiter._history) == 0


def test_token_bucket_limiter():
    """Verify token bucket limiter handles bursts and refills."""
    bucket = TokenBucketLimiter(rate_per_second=10.0, capacity=5.0)

    # Consume full capacity
    d1 = bucket.allow("client-1", tokens=5.0)
    assert d1.allowed is True

    # Immediate next request rejected
    d2 = bucket.allow("client-1", tokens=1.0)
    assert d2.allowed is False
    assert d2.retry_after >= 1

    # Wait for refill of tokens
    time.sleep(0.2)  # 0.2s * 10 tokens/s = 2 tokens refilled
    d3 = bucket.allow("client-1", tokens=1.0)
    assert d3.allowed is True

    bucket.reset()
    assert len(bucket._buckets) == 0


def test_redis_rate_limiter_in_memory_fallback():
    """Verify RedisRateLimiter functions correctly using in-memory fallback."""
    limiter = RedisRateLimiter(redis_url=None, default_limit=2, window_seconds=2)
    d1 = limiter.allow("test-key")
    assert d1.allowed is True

    d2 = limiter.allow("test-key")
    assert d2.allowed is True

    d3 = limiter.allow("test-key")
    assert d3.allowed is False
