"""INTELX Search and LLM Provider Failure Taxonomy, Health Tracking, and Circuit Breaking."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProviderResultStatus(str, Enum):
    """Explicit status classification for provider execution results."""

    SUCCESS_WITH_RESULTS = "SUCCESS_WITH_RESULTS"
    SUCCESS_WITH_NO_RESULTS = "SUCCESS_WITH_NO_RESULTS"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILURE = "AUTH_FAILURE"
    TIMEOUT = "TIMEOUT"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"


class ProviderError(RuntimeError):
    """Raised when an external LLM or Search provider experiences fatal errors."""

    def __init__(self, message: str, status: ProviderResultStatus = ProviderResultStatus.PROVIDER_UNAVAILABLE, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.details = details or {}


@dataclass(slots=True)
class ProviderHealth:
    """Live telemetry and health state for an individual provider."""

    name: str
    available: bool = True
    consecutive_failures: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    cooldown_until: float = 0.0
    reason: str = ""

    def record_success(self) -> None:
        """Update state on successful invocation."""
        self.available = True
        self.consecutive_failures = 0
        self.last_success_at = time.time()
        self.reason = ""

    def record_failure(self, reason: str, cooldown_seconds: float = 30.0) -> None:
        """Record failure and trip circuit breaker if threshold exceeded."""
        self.consecutive_failures += 1
        self.last_failure_at = time.time()
        self.reason = reason
        if self.consecutive_failures >= 3:
            self.available = False
            self.cooldown_until = time.time() + cooldown_seconds

    def is_healthy(self) -> bool:
        """Check if provider is available or has exited cooldown."""
        if not self.available and time.time() > self.cooldown_until:
            self.available = True
            self.consecutive_failures = 0
        return self.available


class ProviderRouter:
    """Routes generation or search tasks across prioritized provider backends."""

    def __init__(self, providers: list[Any]) -> None:
        self.providers = providers

    async def call(self, role: str, request: Any) -> Any:
        """Execute request against healthy providers with fallback."""
        errors: list[str] = []
        for provider in self.providers:
            try:
                if hasattr(provider, "health"):
                    h = provider.health()
                    if not getattr(h, "available", True):
                        continue
                if hasattr(provider, "generate"):
                    return await provider.generate(role, request)
            except Exception as exc:
                errors.append(f"{getattr(provider, 'name', 'provider')}: {exc}")
        raise ProviderError(f"all providers failed safely: {' | '.join(errors)}")
