from __future__ import annotations
import hashlib, hmac, secrets
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Principal:
    actor_id: str
    tenant_id: str
    role: str

class AuthError(ValueError): pass

def hash_api_key(secret_value: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", secret_value.encode(), salt, 300_000).hex()

def secure_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)

def validate_production_secret(secret_value: str | None) -> None:
    if not secret_value or len(secret_value) < 32:
        raise AuthError("production secret is missing or too weak")

def generate_api_key() -> str:
    return secrets.token_urlsafe(32)
