"""INTELX Central SSRF and DNS Rebinding Safe Fetch Gateway."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from intelx.core.errors import PolicyViolationError, SSRFBlockedError

BLOCKED_EXPLICIT_IPS = {
    "169.254.169.254",  # AWS/GCP metadata endpoint
    "169.254.170.2",    # AWS container credentials
    "100.100.100.200",  # Alibaba metadata
    "fd00:ec2::254",    # AWS IPv6 metadata
}


class SSRFBlocked(SSRFBlockedError):
    """Raised when an outbound HTTP request targets a prohibited or unroutable destination."""


def resolve_and_validate(host: str, allow_private: bool = False) -> list[str]:
    """Resolve DNS address set and validate against private, loopback, and metadata ranges."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SSRFBlocked(f"DNS resolution failure for '{host}': {e}") from e

    ips = sorted({item[4][0] for item in infos})
    if not allow_private:
        for raw in ips:
            try:
                ip = ipaddress.ip_address(raw)
            except ValueError:
                continue

            if str(ip) in BLOCKED_EXPLICIT_IPS:
                raise SSRFBlocked(f"resolved explicit metadata endpoint: {raw}")

            # Handle NAT64 / DNS64 Well-Known Prefix (RFC 6052: 64:ff9b::/96)
            if isinstance(ip, ipaddress.IPv6Address) and ip in ipaddress.IPv6Network("64:ff9b::/96"):
                embedded = ipaddress.IPv4Address(ip.packed[-4:])
                if (
                    embedded.is_private
                    or embedded.is_loopback
                    or embedded.is_link_local
                    or embedded.is_reserved
                    or embedded.is_multicast
                    or str(embedded) in BLOCKED_EXPLICIT_IPS
                ):
                    raise SSRFBlocked(f"resolved private NAT64 destination: {embedded}")
                continue

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                raise SSRFBlocked(f"resolved private/reserved target: {raw}")

    return ips


def safe_target(url: str, policy: any = None, allow_private: bool = False) -> str:
    """Validate URL syntax, scheme, policy allowlist, and resolve safely."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFBlocked(f"prohibited URL scheme: '{parsed.scheme}'")

    host = parsed.hostname or ""
    if not host:
        raise SSRFBlocked("empty or invalid URL hostname")

    if policy is not None and hasattr(policy, "validate_url"):
        try:
            policy.validate_url(url)
        except Exception as exc:
            raise SSRFBlocked(f"policy violation: {exc}") from exc

    resolve_and_validate(host, allow_private=allow_private)
    return host
