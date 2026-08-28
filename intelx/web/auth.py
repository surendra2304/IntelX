"""INTELX Web UI Session Management and Cookie Signer."""

import base64
import hashlib
import hmac
import json
from typing import Any

from fastapi import HTTPException, Request, status

from intelx.core.settings import get_settings

COOKIE_NAME = "intelx_session"


def _get_signing_secret() -> bytes:
    settings = get_settings()
    secret = settings.API_KEYS[0] if settings.API_KEYS else "intelx_secret_default_signing_key"
    return secret.encode("utf-8")


def sign_session_data(data: dict[str, Any]) -> str:
    """Sign payload dictionary into base64 url-safe token."""
    raw_json = json.dumps(data, sort_keys=True).encode("utf-8")
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
        return json.loads(raw_json)
    except Exception:
        return None


async def get_web_user(request: Request) -> dict[str, Any] | None:
    """Extract authenticated user session from cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    session_data = verify_session_token(token)
    if not session_data:
        return None
    return session_data


async def require_web_user(request: Request) -> dict[str, Any]:
    """Dependency redirecting anonymous visitors to /login."""
    user = await get_web_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )
    return user
