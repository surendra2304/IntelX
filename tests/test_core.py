"""Tests for core logging sanitization and error handling."""

from intelx.core.errors import IntelXError, NotFoundError
from intelx.core.logging import sanitize_value


def test_sensitive_value_sanitization():
    """Verify recursive dictionary/list secret sanitization."""
    payload = {
        "user": "analyst",
        "api_key": "secret-12345",
        "nested": {
            "token": "tok_abcdef",
            "safe_field": "research report on semiconductors",
        },
        "auth_header": "Bearer top-secret-token",
    }
    sanitized = sanitize_value(payload)
    assert sanitized["user"] == "analyst"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["nested"]["safe_field"] == "research report on semiconductors"
    assert sanitized["auth_header"] == "Bearer [REDACTED]"


def test_custom_errors():
    """Verify IntelX domain exceptions and details serialization."""
    err = NotFoundError("Source document missing", details={"source_id": "src_123"})
    assert isinstance(err, IntelXError)
    assert err.message == "Source document missing"
    assert err.details == {"source_id": "src_123"}


def test_rate_limiter_sliding_window():
    """Verify in-memory sliding window rate limiter behaviour and retry-after calculation."""
    from intelx.core.auth import RateLimiter

    limiter = RateLimiter(default_limit=3, window_seconds=10)
    key_hash = "test_user_hash"

    # First 3 requests must be allowed
    assert limiter.check_rate_limit(key_hash)[0] is True
    assert limiter.check_rate_limit(key_hash)[0] is True
    assert limiter.check_rate_limit(key_hash)[0] is True

    # 4th request must be rejected with retry_after > 0
    allowed, retry_after = limiter.check_rate_limit(key_hash)
    assert allowed is False
    assert retry_after > 0


def test_problem_response_rfc7807():
    """Verify RFC 7807 problem details response format and content type."""
    from intelx.core.auth import problem_response

    resp = problem_response(
        status_code=400,
        type_code="invalid_request",
        title="Invalid Request Format",
        detail="The provided objective was empty",
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"] == "application/problem+json"


def test_length_preserving_redaction():
    """Verify secret redaction preserves exact string length and character offsets."""
    from intelx.core.security import redact_document_text_preserving_length

    text = "Authorization: Bearer my_secret_token_1234567890 for API access."
    redacted, items = redact_document_text_preserving_length(text)

    assert len(redacted) == len(text)
    assert "my_secret_token_1234567890" not in redacted
    assert len(items) > 0

