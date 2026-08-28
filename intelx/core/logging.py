"""INTELX Structured JSON Logging Infrastructure."""

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Context variable for request tracing
request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id_ctx", default=None
)

# Common sensitive keys that must be redacted from log outputs
SENSITIVE_KEYWORDS = {
    "password",
    "secret",
    "api_key",
    "apikey",
    "token",
    "authorization",
    "bearer",
    "private_key",
}


def sanitize_value(val: Any) -> Any:
    """Recursively sanitize values to prevent secret leakage."""
    if isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            if any(s in str(k).lower() for s in SENSITIVE_KEYWORDS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_value(v)
        return sanitized
    elif isinstance(val, list):
        return [sanitize_value(item) for item in val]
    elif isinstance(val, str):
        # Basic check for bearer token patterns
        if val.lower().startswith("bearer "):
            return "Bearer [REDACTED]"
    return val


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line structured JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_ctx.get() or getattr(record, "request_id", None),
        }

        # Include standard exception information if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include custom extra fields if attached to log record
        extra_fields = {}
        standard_attrs = {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "request_id",
        }
        for key, val in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                extra_fields[key] = sanitize_value(val)

        if extra_fields:
            log_entry["extra"] = extra_fields

        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure root and application loggers with JSON formatter."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())

    # Clear existing handlers to prevent duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(console_handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
