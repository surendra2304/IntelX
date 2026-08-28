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
