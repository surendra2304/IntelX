"""INTELX Security Hardening, Log Secret Scrubber, and Character-Preserving Redaction Engine."""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Sensitive secret regex patterns
SECRET_PATTERNS = [
    # Bearer tokens
    (re.compile(r"Bearer\s+([a-zA-Z0-9_\-\.]{15,})", re.IGNORECASE), "BEARER_TOKEN"),
    # OpenAI / API keys starting with sk-
    (re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b"), "OPENAI_KEY"),
    # GitHub Personal Access Tokens
    (re.compile(r"\b(ghp_[a-zA-Z0-9]{20,})\b"), "GITHUB_TOKEN"),
    # AWS Access Key IDs
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "AWS_ACCESS_KEY"),
    # Generic API Key / Secret assignments
    (
        re.compile(
            r"""(?i)(?:api[_-]?key|secret|password|auth[_-]?token|access[_-]?token)\s*[:=]\s*['"]?([a-zA-Z0-9_\-\.]{14,})['"]?"""
        ),
        "GENERIC_SECRET",
    ),
]


def scrub_secrets(text: str) -> str:
    """Scrub sensitive keys, passwords, and authorization tokens from text."""
    if not text or not isinstance(text, str):
        return text

    scrubbed = text
    for pattern, label in SECRET_PATTERNS:

        def _repl(match: re.Match, lbl: str = label) -> str:
            full_match = match.group(0)
            secret_val = match.group(1) if match.groups() else full_match
            return full_match.replace(secret_val, f"[REDACTED:{lbl}]")

        scrubbed = pattern.sub(_repl, scrubbed)
    return scrubbed


def redact_document_text_preserving_length(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Redact high-entropy secrets from document text while preserving EXACT character offsets."""
    if not text:
        return text, []

    redactions: list[dict[str, Any]] = []
    redacted_chars = list(text)

    for pattern, label in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            start_pos = match.start(1) if match.groups() else match.start(0)
            end_pos = match.end(1) if match.groups() else match.end(0)
            length = end_pos - start_pos

            tag = f"[REDACTED:{label}]"
            if len(tag) <= length:
                replacement = tag + (" " * (length - len(tag)))
            else:
                replacement = "[REDACTED]"[:length]

            redacted_chars[start_pos:end_pos] = list(replacement)
            redactions.append(
                {
                    "type": label,
                    "start": start_pos,
                    "end": end_pos,
                    "original_length": length,
                }
            )

    return "".join(redacted_chars), redactions


class LogScrubberFilter(logging.Filter):
    """Logging filter that scrubs sensitive credentials from all log output."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: scrub_secrets(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    scrub_secrets(str(arg)) if isinstance(arg, str) else arg for arg in record.args
                )
        return True


def install_log_scrubber() -> None:
    """Attach the LogScrubberFilter globally to the root logger and all handlers."""
    root_logger = logging.getLogger()
    scrubber = LogScrubberFilter()
    root_logger.addFilter(scrubber)
    for handler in root_logger.handlers:
        handler.addFilter(scrubber)
