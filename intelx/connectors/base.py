"""INTELX Connector Base Class and Security Interfaces."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from intelx.core.errors import DomainPolicyError
from intelx.core.settings import Settings, get_settings


def default_policy_guard(domain: str, settings: Settings | None = None) -> bool:
    """Default security guard checking domain allowlist and denylist."""
    cfg = settings or get_settings()
    normalized = domain.lower().strip()

    # 1. Denylist check
    for denied in cfg.DOMAIN_DENYLIST:
        denied_norm = denied.lower().strip()
        if denied_norm and (normalized == denied_norm or normalized.endswith(f".{denied_norm}")):
            return False

    # 2. Allowlist check (if non-empty, only allowlisted domains allowed)
    if cfg.DOMAIN_ALLOWLIST:
        allowed = False
        for allow in cfg.DOMAIN_ALLOWLIST:
            allow_norm = allow.lower().strip()
            if allow_norm and (normalized == allow_norm or normalized.endswith(f".{allow_norm}")):
                allowed = True
                break
        if not allowed:
            return False

    return True


class BaseConnector(ABC):
    """Abstract base connector with policy guards, budget checks, and telemetry."""

    def __init__(
        self,
        name: str,
        capabilities: list[str],
        required_credentials: list[str],
        classification: str,
        policy_guard: Callable[[str], bool] | None = None,
        budget_guard: Callable[..., bool] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.name = name
        self.capabilities = capabilities
        self.required_credentials = required_credentials
        self.classification = classification
        self.settings = settings or get_settings()
        self.policy_guard = policy_guard or (lambda d: default_policy_guard(d, self.settings))
        self.budget_guard = budget_guard

    def check_policy(self, domain: str) -> None:
        """Validate target domain against connector policy guard."""
        if not self.policy_guard(domain):
            raise DomainPolicyError(
                f"Domain '{domain}' is blocked by policy guard rules",
                details={"domain": domain, "connector": self.name},
            )

    def check_budget(self, **kwargs: Any) -> None:
        """Perform budget preflight check if configured."""
        if self.budget_guard and not self.budget_guard(**kwargs):
            raise DomainPolicyError(
                f"Budget limits exceeded for connector {self.name}",
                details={"connector": self.name},
            )

    @abstractmethod
    async def fetch(self, target: str, **kwargs: Any) -> Any:
        """Execute connector fetch operation."""
        pass
