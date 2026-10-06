"""Shared SSRF validation for outbound HTTP targets."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit

from intelx.core.errors import SSRFBlockedError

BLOCKED_EXPLICIT_IPS = {
    "169.254.169.254",  # AWS/GCP metadata endpoint
    "169.254.170.2",  # AWS container credentials
    "100.100.100.200",  # Alibaba metadata
    "fd00:ec2::254",  # AWS IPv6 metadata
}


class SSRFBlocked(SSRFBlockedError):
    """Raised when an outbound HTTP request targets a prohibited or unroutable destination."""


def _is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is not globally routable or is explicitly sensitive."""
    if str(address) in BLOCKED_EXPLICIT_IPS:
        return True
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return _is_blocked_address(address.ipv4_mapped)
        if address in ipaddress.IPv6Network("64:ff9b::/96"):
            embedded = ipaddress.IPv4Address(address.packed[-4:])
            return _is_blocked_address(embedded)
    return not address.is_global


def resolve_and_validate(
    host: str,
    allow_private: bool = False,
    port: int | None = None,
) -> list[str]:
    """Resolve a host and reject DNS errors, empty answers, and unsafe addresses."""
    if not host or host.strip() != host:
        raise SSRFBlocked("empty or malformed target hostname")

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SSRFBlocked(f"DNS resolution failure for '{host}': {exc}") from exc

    ips = sorted({item[4][0].split("%", 1)[0] for item in infos if item[4]})
    if not ips:
        raise SSRFBlocked(f"DNS resolution returned no addresses for '{host}'")

    for raw in ips:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise SSRFBlocked(f"DNS returned an invalid address for '{host}'") from exc
        if str(address) in BLOCKED_EXPLICIT_IPS or (
            not allow_private and _is_blocked_address(address)
        ):
            raise SSRFBlocked(f"resolved private/reserved target: {raw}")

    return ips


def safe_target(url: str, policy: Any = None, allow_private: bool = False) -> str:
    """Validate URL syntax, policy allowlist, DNS resolution, and resolved addresses."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in ("http", "https"):
            raise SSRFBlocked(f"prohibited URL scheme: '{parsed.scheme}'")
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise SSRFBlocked("empty hostname or user information in target URL")
        # Accessing .port also validates malformed/out-of-range port syntax.
        _ = parsed.port
    except ValueError as exc:
        if isinstance(exc, SSRFBlocked):
            raise
        raise SSRFBlocked(f"invalid target URL: {exc}") from exc

    host = parsed.hostname.rstrip(".")
    if policy is not None and hasattr(policy, "validate_url"):
        try:
            policy.validate_url(url)
        except Exception as exc:
            raise SSRFBlocked(f"policy violation: {exc}") from exc

    resolve_and_validate(host, allow_private=allow_private)
    return host
