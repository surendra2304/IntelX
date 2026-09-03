from __future__ import annotations
import socket
from .policy import PolicyViolation

class SSRFBlocked(PolicyViolation): pass

def resolve_and_validate(host: str, allow_private=False) -> list[str]:
    infos=socket.getaddrinfo(host, None)
    ips=sorted({item[4][0] for item in infos})
    if not allow_private:
        import ipaddress
        for raw in ips:
            ip=ipaddress.ip_address(raw)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise SSRFBlocked(f"resolved private/reserved target: {raw}")
    return ips

def safe_target(url: str, policy, allow_private=False):
    try:
        host=policy.validate_url(url)
    except PolicyViolation as exc:
        raise SSRFBlocked(str(exc)) from exc
    resolve_and_validate(host, allow_private)
    return host
