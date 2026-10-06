"""INTELX Web UI Session Management and Cookie Signer."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from intelx.core.settings import get_settings
from intelx.db.models import ApiKey
from intelx.db.session import get_sessionmaker

COOKIE_NAME = "intelx_session"
_DEVELOPMENT_SESSION_SECRET = secrets.token_bytes(32)


def _get_signing_secret() -> bytes:
    settings = get_settings()
    secret = settings.SECRET_KEY
    if not secret or len(secret) < 32:
        if settings.is_production():
            raise RuntimeError(
                "Configure a unique INTELX_SECRET_KEY of at least 32 characters before signing web sessions."
            )
        return _DEVELOPMENT_SESSION_SECRET
    return secret.encode("utf-8")


def sign_session_data(data: dict[str, Any]) -> str:
    """Sign a bounded-lifetime payload into a base64 URL-safe token."""
    payload = dict(data)
    now = int(time.time())
    payload.setdefault("iat", now)
    payload.setdefault("exp", now + max(1, get_settings().SESSION_TTL_SECONDS))
    raw_json = json.dumps(payload, sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw_json).decode("utf-8")
    signature = hmac.new(
        _get_signing_secret(), b64_payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{b64_payload}.{signature}"


def verify_session_token(token: str) -> dict[str, Any] | None:
    """Verify HMAC signature and decode session dictionary."""
    if not token or "." not in token:
        return None
    b64_payload, signature = token.rsplit(".", 1)
    expected_sig = hmac.new(
        _get_signing_secret(), b64_payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_sig):
        return None
    try:
        raw_json = base64.urlsafe_b64decode(b64_payload.encode("utf-8")).decode("utf-8")
        session_data = json.loads(raw_json)
        if not isinstance(session_data, dict) or int(session_data.get("exp", 0)) <= int(
            time.time()
        ):
            return None
        return session_data
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


async def get_web_user(request: Request) -> dict[str, Any] | None:
    """Extract a valid, unrevoked API principal from the signed session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    session_data = verify_session_token(token)
    key_hash = session_data.get("key_hash") if session_data else None
    if not key_hash:
        return None

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
        api_key = result.scalar_one_or_none()
        if not api_key or api_key.revoked:
            return None
        role = api_key.role.value if hasattr(api_key.role, "value") else str(api_key.role)
        return {"key_hash": key_hash, "name": api_key.name, "role": role.upper()}


async def require_web_user(request: Request) -> dict[str, Any]:
    """Dependency redirecting anonymous visitors to /login."""
    user = await get_web_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )
    return user
