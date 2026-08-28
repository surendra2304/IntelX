"""INTELX Core Package."""

from intelx.core.confidence import compute_confidence_score, get_confidence_label
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
from intelx.core.independence import compute_3gram_jaccard, is_independent_evidence
from intelx.core.logging import setup_logging
from intelx.core.settings import Settings, get_settings
from intelx.core.version import PROJECT_NAME, __version__

__all__ = [
    "__version__",
    "PROJECT_NAME",
    "Settings",
    "get_settings",
    "setup_logging",
    "compute_confidence_score",
    "get_confidence_label",
    "compute_3gram_jaccard",
    "is_independent_evidence",
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
