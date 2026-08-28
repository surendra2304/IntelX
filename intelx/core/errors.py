"""INTELX Error Definitions and Exception Handlers."""

import logging
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class IntelXError(Exception):
    """Base exception for all INTELX platform errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigError(IntelXError):
    """Raised when configuration or settings validation fails."""


class DatabaseError(IntelXError):
    """Raised when database operations encounter fatal errors."""


class NotFoundError(IntelXError):
    """Raised when a requested resource is not found."""


class ValidationError(IntelXError):
    """Raised when input validation fails."""


class IntegrityError(IntelXError):
    """Raised when evidence span quote does not match exact document text slice."""


class ProviderError(IntelXError):
    """Raised when an external LLM or search provider fails."""


class BudgetExceededError(IntelXError):
    """Raised when execution limits or budgets are exceeded."""


class StructuredOutputError(IntelXError):
    """Raised when model response fails schema validation after retry."""


async def intelx_exception_handler(request: Request, exc: IntelXError) -> JSONResponse:
    """Handle custom IntelX errors gracefully."""
    logger.error(
        f"Handled IntelX error: {exc.message}",
        extra={"details": exc.details, "error_type": exc.__class__.__name__},
    )
    status_code = status.HTTP_400_BAD_REQUEST
    if isinstance(exc, NotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, BudgetExceededError):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "type": exc.__class__.__name__,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled unexpected exceptions."""
    logger.exception(f"Unhandled server error: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "type": "InternalServerError",
                "message": "An unexpected error occurred during request processing.",
            }
        },
    )
