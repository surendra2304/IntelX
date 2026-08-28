"""INTELX Core Package."""

from intelx.core.errors import (
    BudgetExceededError,
    ConfigError,
    ContentSizeExceededError,
    DatabaseError,
    DomainPolicyError,
    IntegrityError,
    IntelXError,
    NotFoundError,
    ProviderError,
    RobotsDisallowedError,
    SecurityError,
    SSRFBlockedError,
    StructuredOutputError,
    UnsupportedContentTypeError,
    ValidationError,
)
from intelx.core.logging import setup_logging
from intelx.core.settings import Settings, get_settings
from intelx.core.version import PROJECT_NAME, __version__

__all__ = [
    "__version__",
    "PROJECT_NAME",
    "Settings",
    "get_settings",
    "setup_logging",
    "IntelXError",
    "ConfigError",
    "DatabaseError",
    "IntegrityError",
    "NotFoundError",
    "ValidationError",
    "ProviderError",
    "BudgetExceededError",
    "StructuredOutputError",
    "SecurityError",
    "SSRFBlockedError",
    "RobotsDisallowedError",
    "ContentSizeExceededError",
    "UnsupportedContentTypeError",
    "DomainPolicyError",
]
