from __future__ import annotations
from dataclasses import dataclass

class TenantViolation(PermissionError): pass

@dataclass(frozen=True,slots=True)
class Principal:
    tenant_id:str
    actor_id:str
    scopes:frozenset[str]=frozenset()

class TenantBoundary:
    def require(self,principal:Principal,tenant_id:str)->None:
        if principal.tenant_id!=tenant_id: raise TenantViolation("cross-tenant access denied")
    def require_scope(self,principal:Principal,scope:str)->None:
        if scope not in principal.scopes and "*" not in principal.scopes: raise TenantViolation("scope denied")
