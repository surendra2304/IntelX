"""INTELX API Key Authentication, Multi-Tenant Principal Resolution, and Rate Limiting."""

import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import ApiKeyRole
from intelx.core.settings import Settings, get_settings
from intelx.db.models import ApiKey
from intelx.db.session import get_sessionmaker

logger = logging.getLogger("intelx.auth")


class AuthError(Exception):
    """Authentication or authorization failure."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Typed security principal representing an authenticated caller."""

    tenant_id: str = "default"
    actor_id: str = "anonymous"
    scopes: frozenset[str] = frozenset({"*"})
    roles: tuple[str, ...] = ("member",)
    credential_id: str | None = None
    environment: str = "development"

    def has_scope(self, scope: str) -> bool:
        """Check if principal possesses a specific scope or wildcard."""
        return "*" in self.scopes or scope in self.scopes

    def has_role(self, role: str) -> bool:
        """Check if principal possesses a role."""
        return role in self.roles or "admin" in self.roles


class ProblemDetails(BaseModel):
    """RFC 7807 Problem Details representation."""

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None
    invalid_params: list[dict[str, Any]] | None = None


def problem_response(
    status_code: int,
    type_code: str,
    title: str,
    detail: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Construct RFC 7807 problem+json HTTP response."""
    content = {
        "type": f"intelx:{type_code}",
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    hdrs = {"Content-Type": "application/problem+json"}
    if headers:
        hdrs.update(headers)
    return JSONResponse(status_code=status_code, content=content, headers=hdrs)


def hash_api_key(raw: str, salt: bytes | None = None) -> str:
    """Compute secure hash of API key using PBKDF2 HMAC SHA-256."""
    cleaned = raw.strip().encode("utf-8")
    if salt is not None:
        derived = hashlib.pbkdf2_hmac("sha256", cleaned, salt, 100_000)
        return f"{salt.hex()}${derived.hex()}"
    return hashlib.sha256(cleaned).hexdigest()


def secure_compare(val_a: str, val_b: str) -> bool:
    """Constant-time string comparison preventing timing attacks."""
    return hmac.compare_digest(val_a.strip(), val_b.strip())


def generate_api_key(prefix: str = "ix_live_") -> str:
    """Generate a high-entropy cryptographically secure API key."""
    return f"{prefix}{secrets.token_urlsafe(32)}"


def validate_production_secret(secret: str) -> bool:
    """Validate that production secrets satisfy length and complexity bounds."""
    if len(secret) < 16:
        return False
    if secret.lower() in ("secret", "password", "intelx-super-secret-key-change-in-production", "change-me", "dev-admin-key"):
        return False
    return True


class RateLimiter:
    """In-memory sliding window rate limiter per API key hash."""

    def __init__(self, default_limit: int = 120, window_seconds: int = 60) -> None:
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = defaultdict(list)

    def check_rate_limit(self, key_hash: str, limit: int | None = None) -> tuple[bool, int]:
        """Return (is_allowed, retry_after_seconds)."""
        now = time.time()
        max_reqs = limit or self.default_limit
        cutoff = now - self.window_seconds

        # Prune old timestamps
        timestamps = [ts for ts in self._history[key_hash] if ts > cutoff]
        self._history[key_hash] = timestamps

        if len(timestamps) >= max_reqs:
            oldest = timestamps[0]
            retry_after = max(1, int(self.window_seconds - (now - oldest)))
            return False, retry_after

        self._history[key_hash].append(now)
        return True, 0


rate_limiter = RateLimiter(default_limit=120, window_seconds=60)
friday_rate_limiter = RateLimiter(default_limit=50, window_seconds=3600)


async def seed_api_keys_from_settings(session: AsyncSession, settings: Settings) -> None:
    """Seed configured API keys from settings into database on startup."""
    # Enforce strict production rules
    if settings.is_production():
        settings.validate_production_security()

    keys = list(settings.API_KEYS) if settings.API_KEYS else []
    if getattr(settings, "INTELX_API_KEY", None) and settings.INTELX_API_KEY not in keys:
        keys.append(settings.INTELX_API_KEY)

    # Only seed development demo keys in development or test environments
    if settings.is_dev_or_test():
        for default_k in ["dev-admin-key", "dev-member-key", "intelx_dev_secret_key_admin"]:
            if default_k not in keys:
                keys.append(default_k)

    if settings.FRIDAY_API_KEY and settings.FRIDAY_API_KEY not in keys:
        keys.append(settings.FRIDAY_API_KEY)

    for idx, raw_key in enumerate(keys):
        k_hash = hash_api_key(raw_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == k_hash)
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()
        if not existing:
            role = ApiKeyRole.ADMIN if (idx == 0 or "admin" in raw_key) else ApiKeyRole.MEMBER
            name = (
                "friday-delegation"
                if (settings.FRIDAY_API_KEY and raw_key == settings.FRIDAY_API_KEY)
                else ("env-seeded-admin" if role == ApiKeyRole.ADMIN else f"env-seeded-{idx}")
            )
            new_key = ApiKey(
                key_hash=k_hash,
                name=name,
                role=role,
                created_at=datetime.now(UTC),
            )
            session.add(new_key)
    await session.commit()


async def get_current_api_key(
    request: Request,
    authorization: str | None = Header(None, description="Bearer <api_key>"),
) -> ApiKey:
    """Validate Bearer API key header and enforce sliding window rate limit."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected 'Bearer <key>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = authorization.replace("Bearer ", "").strip()
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty API key token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_hash = hash_api_key(raw_token)

    # 1. Rate Limit Check (120 req/min)
    allowed, retry_after = rate_limiter.check_rate_limit(key_hash)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded (120 requests/minute). Retry after {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    # 2. Database Lookup
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        res = await session.execute(stmt)
        api_key = res.scalar_one_or_none()
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if api_key.revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return api_key


async def get_current_principal(
    request: Request,
    api_key: ApiKey = Depends(get_current_api_key),
) -> Principal:
    """Resolve the authenticated request to a typed Principal with tenant & scopes."""
    settings = get_settings()
    tenant_id = getattr(api_key, "tenant_id", None) or "default"
    role_str = api_key.role.value if hasattr(api_key.role, "value") else str(api_key.role)
    scopes = frozenset({"*"}) if role_str == "admin" else frozenset({"research:run", "research:view", "source:fetch"})

    return Principal(
        tenant_id=tenant_id,
        actor_id=api_key.id or api_key.name,
        scopes=scopes,
        roles=(role_str,),
        credential_id=api_key.id,
        environment=settings.ENV,
    )


async def get_friday_api_key(
    request: Request,
    authorization: str | None = Header(None, description="Bearer <api_key>"),
    x_api_key: str | None = Header(None, alias="X-API-Key", description="Friday API Key"),
) -> ApiKey:
    """Validate Friday API Key and enforce 50 req/hour rate limit."""
    raw_token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "").strip()
    elif x_api_key:
        raw_token = x_api_key.strip()
    elif authorization:
        raw_token = authorization.strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Friday API Key. Provide via 'Authorization: Bearer <key>' or 'X-API-Key: <key>' header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    key_hash = hash_api_key(raw_token)

    # 1. Rate Limit Check (50 req/hour)
    allowed, retry_after = friday_rate_limiter.check_rate_limit(key_hash, limit=50)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Friday API rate limit exceeded (50 requests/hour). Retry after {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    # 2. Direct Match with INTELX_FRIDAY_API_KEY
    if settings.FRIDAY_API_KEY and raw_token == settings.FRIDAY_API_KEY:
        return ApiKey(
            id="friday-env-key",
            key_hash=key_hash,
            name="friday-direct-key",
            role=ApiKeyRole.MEMBER,
            created_at=datetime.now(UTC),
        )

    # 3. Database Lookup
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        res = await session.execute(stmt)
        api_key = res.scalar_one_or_none()
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Friday API Key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return api_key


def require_role(required_role: ApiKeyRole | str):
    """Dependency factory checking if authenticated API key meets minimum role tier."""

    async def _role_checker(api_key: ApiKey = Depends(get_current_api_key)) -> ApiKey:
        req_val = (
            required_role.value if isinstance(required_role, ApiKeyRole) else str(required_role)
        )
        if req_val == ApiKeyRole.ADMIN.value and api_key.role != ApiKeyRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action requires '{req_val}' role, but key has '{api_key.role.value}'",
            )
        return api_key

    return _role_checker


def require_scope(required_scope: str):
    """Dependency factory checking if authenticated caller has required scope."""

    async def _scope_checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.has_scope(required_scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action requires scope '{required_scope}'",
            )
        return principal

    return _scope_checker


def require_tenant(target_tenant_id: str):
    """Dependency factory checking if caller has access to tenant."""

    async def _tenant_checker(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.tenant_id != target_tenant_id and "*" not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cross-tenant access to '{target_tenant_id}' denied",
            )
        return principal

    return _tenant_checker
