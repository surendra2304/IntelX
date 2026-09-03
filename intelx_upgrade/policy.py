from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse
from ipaddress import ip_address
import socket

@dataclass(frozen=True, slots=True)
class DomainPolicy:
    allow_domains: frozenset[str] = frozenset()
    deny_domains: frozenset[str] = frozenset()
    allow_private_ips: bool = False
    max_sources: int = 50
    max_fetches: int = 60
    max_cost_usd: float = 10.0

class PolicyViolation(ValueError): pass

class ResearchPolicy:
    def __init__(self, config: DomainPolicy):
        self.config = config

    def validate_url(self, url: str) -> str:
        p = urlparse(url)
        if p.scheme not in {"http", "https"} or not p.hostname:
            raise PolicyViolation("only http/https URLs are permitted")
        host = p.hostname.lower().rstrip(".")
        for denied in self.config.deny_domains:
            if host == denied or host.endswith("." + denied):
                raise PolicyViolation(f"domain denied: {host}")
        if self.config.allow_domains:
            if not any(host == a or host.endswith("." + a) for a in self.config.allow_domains):
                raise PolicyViolation(f"domain not allowlisted: {host}")
        if not self.config.allow_private_ips:
            try:
                ip = ip_address(host)
            except ValueError:
                ip = None
            if ip and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
                raise PolicyViolation("private or loopback IP target denied")
        return host

    def validate_source_count(self, count: int) -> None:
        if count > self.config.max_sources:
            raise PolicyViolation("source budget exceeded")

    def validate_fetch_count(self, count: int) -> None:
        if count >= self.config.max_fetches:
            raise PolicyViolation("fetch budget exceeded")
