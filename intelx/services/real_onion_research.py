"""Offline Robin-inspired OSINT result processing. No network or Tor access.

External page titles and URLs are untrusted evidence, never instructions.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


@dataclass(frozen=True)
class ResearchHit:
    title: str
    url: str


@dataclass
class ResearchBatch:
    hits: list[ResearchHit]
    raw_count: int
    rejected_count: int
    duplicate_count: int
    capped_count: int
    distinct_hosts: int


class OnionResearchEngine:
    """Validate destinations, unwrap engine links and preserve host diversity."""

    TRACKING = frozenset({"utm", "ref", "referrer", "fbclid", "gclid", "yclid", "msclkid", "src"})

    def validate(self, url: str, allow_clearweb: bool = False) -> str:
        """Return a normalized URL or raise; reject ambiguous URL authorities."""
        if not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url) or "\\" in url:
            raise ValueError("ambiguous URL")
        try:
            parts = urlsplit(url)
            host = parts.hostname
            port = parts.port
        except ValueError as error:
            raise ValueError("invalid authority") from error
        if parts.scheme not in {"http", "https"} or not host or parts.username is not None or parts.password is not None:
            raise ValueError("HTTP(S) URL without userinfo required")
        host = host.lower()
        if not re.fullmatch(r"[a-z0-9.-]+", host) or host.startswith(".") or ".." in host:
            raise ValueError("invalid hostname")
        if not allow_clearweb and not host.endswith(".onion"):
            raise ValueError("non-onion destination refused")
        authority = host + (f":{port}" if port is not None else "")
        return urlunsplit((parts.scheme, authority, parts.path or "/", parts.query, ""))

    def extract_target(self, href: str, engine_url: str) -> str | None:
        """Unwrap one redirect query layer only when it belongs to the engine."""
        engine = self.validate(engine_url)
        try:
            absolute = urljoin(engine, href)
            parts = urlsplit(absolute)
            if parts.hostname == urlsplit(engine).hostname:
                candidates = [value for _, value in parse_qsl(parts.query)]
            else:
                candidates = [absolute]
            for candidate in candidates:
                try:
                    target = self.validate(candidate)
                except ValueError:
                    continue
                if urlsplit(target).hostname != urlsplit(engine).hostname:
                    return target
        except ValueError:
            return None
        return None

    def canonical_key(self, url: str) -> str:
        parts = urlsplit(self.validate(url))
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if k.lower() not in self.TRACKING and not k.lower().startswith("utm_")]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(query)), ""))

    def process(self, hits: list[ResearchHit], per_host_limit: int = 3) -> ResearchBatch:
        if per_host_limit < 1:
            raise ValueError("per_host_limit must be positive")
        seen: set[str] = set()
        hosts: Counter = Counter()
        kept: list[ResearchHit] = []
        rejected = duplicates = capped = 0
        for hit in hits:
            title = " ".join("".join(c for c in hit.title if c.isprintable() or c.isspace()).split())
            try:
                url = self.validate(hit.url)
                key = self.canonical_key(url)
            except ValueError:
                rejected += 1
                continue
            if len(title) < 4 or not any(c.isalnum() for c in title):
                rejected += 1
                continue
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            host = urlsplit(url).hostname
            if hosts[host] >= per_host_limit:
                capped += 1
                continue
            hosts[host] += 1
            kept.append(ResearchHit(title[:200], url))
        return ResearchBatch(kept, len(hits), rejected, duplicates, capped, len(hosts))
