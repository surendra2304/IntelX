"""INTELX Multi-Tenant Isolation and Principal Scoping."""

from __future__ import annotations

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
            raise TenantViolation(f"scope denied: required '{scope}', granted {set(principal.scopes)}")

    def filter_query(self, query: Any, principal: Principal, tenant_column: Any) -> Any:
        """Apply tenant predicate filter to SQLAlchemy query unless wildcard principal."""
        if "*" in principal.scopes and principal.tenant_id == "admin":
            return query
        return query.where(tenant_column == principal.tenant_id)
