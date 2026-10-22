"""INTELX Search and LLM Provider Failure Taxonomy, Health Tracking, and Circuit Breaking."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProviderResultStatus(StrEnum):
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


class CircuitState(StrEnum):
    """State of the circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ProviderError(RuntimeError):
    """Raised when an external LLM or Search provider experiences fatal errors."""

    def __init__(
        self,
        message: str,
        status: ProviderResultStatus = ProviderResultStatus.PROVIDER_UNAVAILABLE,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.details = details or {}


@dataclass(slots=True)
class ProviderHealth:
    """Live telemetry and health state for an individual provider."""

    name: str
    available: bool = True
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    failure_threshold: int = 3
    success_threshold: int = 2
    consecutive_successes: int = 0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    cooldown_seconds: float = 30.0
    cooldown_until: float = 0.0
    total_calls: int = 0
    total_failures: int = 0
    reason: str = ""

    def record_success(self) -> None:
        """Update state on successful invocation."""
        self.total_calls += 1
        self.last_success_at = time.time()
        self.reason = ""

        if self.state == CircuitState.HALF_OPEN:
            self.consecutive_successes += 1
            if self.consecutive_successes >= self.success_threshold:
                self.state = CircuitState.CLOSED
                self.available = True
                self.consecutive_failures = 0
        else:
            self.available = True
            self.consecutive_failures = 0
            self.state = CircuitState.CLOSED

    def record_failure(self, reason: str) -> None:
        """Record failure and trip circuit breaker if threshold exceeded."""
        self.total_calls += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_at = time.time()
        self.reason = reason

        if self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
            if self.consecutive_failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.available = False
                self.cooldown_until = time.time() + self.cooldown_seconds

    def is_healthy(self) -> bool:
        """Check if provider is available or ready for half-open canary testing."""
        now = time.time()
        if self.state == CircuitState.OPEN:
            if now > self.cooldown_until:
                self.state = CircuitState.HALF_OPEN
                self.consecutive_successes = 0
                return True
            return False
        return self.available

    def reset(self) -> None:
        """Reset circuit breaker metrics to initial healthy state."""
        self.available = True
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.cooldown_until = 0.0
        self.reason = ""


class ProviderRouter:
    """Routes generation or search tasks across prioritized provider backends."""

    def __init__(self, providers: list[Any]) -> None:
        self.providers = providers

    async def call(self, role: str, request: Any) -> Any:
        """Execute request against healthy providers with fallback."""
        errors: list[str] = []
        for provider in self.providers:
            name = getattr(provider, "name", "unknown")
            health: ProviderHealth | None = getattr(provider, "health", None)
            if callable(health):
                health = health()

            if health is not None and not health.is_healthy():
                continue

            try:
                if hasattr(provider, "generate"):
                    res = await provider.generate(role, request)
                    if health is not None:
                        health.record_success()
                    return res
                elif hasattr(provider, "fetch"):
                    res = await provider.fetch(request)
                    if health is not None:
                        health.record_success()
                    return res
            except Exception as exc:
                if health is not None:
                    health.record_failure(str(exc))
                errors.append(f"{name}: {exc}")

        raise ProviderError(
            f"all providers failed safely: {' | '.join(errors) if errors else 'no healthy providers available'}",
            status=ProviderResultStatus.PROVIDER_UNAVAILABLE,
            details={"attempted_providers": [getattr(p, "name", str(p)) for p in self.providers]},
        )

    def get_provider_health(self) -> dict[str, dict[str, Any]]:
        """Return health diagnostics across all managed providers."""
        diagnostics = {}
        for p in self.providers:
            name = getattr(p, "name", "unknown")
            h = getattr(p, "health", None)
            if callable(h):
                h = h()
            if h is not None and isinstance(h, ProviderHealth):
                diagnostics[name] = {
                    "available": h.available,
                    "state": h.state,
                    "consecutive_failures": h.consecutive_failures,
                    "total_calls": h.total_calls,
                    "total_failures": h.total_failures,
                    "reason": h.reason,
                }
            else:
                diagnostics[name] = {"available": True, "state": "UNKNOWN"}
        return diagnostics


__all__ = [
    "ProviderResultStatus",
    "CircuitState",
    "ProviderError",
    "ProviderHealth",
    "ProviderRouter",
]
