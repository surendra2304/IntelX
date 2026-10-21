"""INTELX Multi-Tenant Isolation and Principal Scoping."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


class TenantViolation(PermissionError):
    """Raised when cross-tenant access is attempted without authorization."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Security identity carrying tenant boundary, actor identity, and granted scopes."""

    tenant_id: str
    actor_id: str
    scopes: frozenset[str] = frozenset()
    roles: tuple[str, ...] = ("member",)
    credential_id: str | None = None
    environment: str = "development"

    def has_scope(self, scope: str) -> bool:
        """Check if principal possesses a specific scope or wildcard."""
        return "*" in self.scopes or scope in self.scopes

    def has_role(self, role: str) -> bool:
        """Check if principal possesses a role."""
        return role in self.roles or "admin" in self.roles


_CURRENT_PRINCIPAL: ContextVar[Principal | None] = ContextVar("current_principal", default=None)


def get_current_principal() -> Principal | None:
    """Retrieve current ambient security principal."""
    return _CURRENT_PRINCIPAL.get()


def set_current_principal(principal: Principal | None) -> None:
    """Set current ambient security principal."""
    _CURRENT_PRINCIPAL.set(principal)


class TenantContext:
    """Context manager for binding an active security principal to execution context."""

    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self._token: Any = None

    def __enter__(self) -> Principal:
        self._token = _CURRENT_PRINCIPAL.set(self.principal)
        return self.principal

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._token is not None:
            _CURRENT_PRINCIPAL.reset(self._token)


def system_principal() -> Principal:
    """Create a privileged system-internal principal with full scopes."""
    return Principal(
        tenant_id="system",
        actor_id="system-internal",
        scopes=frozenset(["*"]),
        roles=("admin", "system"),
        environment="production",
    )


def admin_principal(tenant_id: str = "admin", actor_id: str = "admin-user") -> Principal:
    """Create an administrative principal for tenant management."""
    return Principal(
        tenant_id=tenant_id,
        actor_id=actor_id,
        scopes=frozenset(["*"]),
        roles=("admin",),
        environment="production",
    )


def member_principal(tenant_id: str, actor_id: str, scopes: list[str] | None = None) -> Principal:
    """Create a scoped tenant member principal."""
    return Principal(
        tenant_id=tenant_id,
        actor_id=actor_id,
        scopes=frozenset(scopes or ["research:read", "research:write"]),
        roles=("member",),
        environment="production",
    )


class TenantBoundary:
    """Enforces strict tenant isolation and scope checks."""

    def require(self, principal: Principal, tenant_id: str) -> None:
        """Enforce that principal matches target tenant or has wildcard scope."""
        if principal.tenant_id != tenant_id and "*" not in principal.scopes:
            raise TenantViolation(
                f"cross-tenant access denied: caller tenant '{principal.tenant_id}' != target '{tenant_id}'"
            )

    def require_scope(self, principal: Principal, scope: str) -> None:
        """Enforce that principal possesses the requested permission scope."""
        if scope not in principal.scopes and "*" not in principal.scopes:
            raise TenantViolation(
                f"scope denied: required '{scope}', granted {set(principal.scopes)}"
            )

    def filter_query(self, query: Any, principal: Principal, tenant_column: Any) -> Any:
        """Apply tenant predicate filter to SQLAlchemy query unless wildcard principal."""
        if "*" in principal.scopes and principal.tenant_id in ("admin", "system"):
            return query
        return query.where(tenant_column == principal.tenant_id)


__all__ = [
    "TenantViolation",
    "Principal",
    "TenantContext",
    "TenantBoundary",
    "get_current_principal",
    "set_current_principal",
    "system_principal",
    "admin_principal",
    "member_principal",
]
