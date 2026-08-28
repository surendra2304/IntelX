"""INTELX API Key Authentication, Rate Limiting, and RFC 7807 Error Handling."""

import hashlib
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import ApiKeyRole
from intelx.core.settings import Settings
from intelx.db.models import ApiKey
from intelx.db.session import get_sessionmaker


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


def hash_api_key(key: str) -> str:
    """Compute deterministic SHA256 hex digest of secret API key."""
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()


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


async def seed_api_keys_from_settings(session: AsyncSession, settings: Settings) -> None:
    """Seed configured API keys from settings into database on startup."""
    keys = settings.API_KEYS
    if not keys:
        # Default dev master key
        keys = ["intelx_dev_secret_key_admin"]

    for idx, raw_key in enumerate(keys):
        k_hash = hash_api_key(raw_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == k_hash)
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()
        if not existing:
            role = ApiKeyRole.ADMIN if (idx == 0 or "admin" in raw_key) else ApiKeyRole.MEMBER
            name = "env-seeded-admin" if role == ApiKeyRole.ADMIN else f"env-seeded-{idx}"
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

    # 1. Rate Limit Check
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
