from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
import hashlib, re

@dataclass(frozen=True, slots=True)
class NormalizedSource:
    url: str
    canonical_url: str
    domain: str
    content_hash: str

class EvidenceNormalizer:
    def normalize_url(self, url: str) -> str:
        p = urlsplit(url.strip())
        scheme = p.scheme.lower()
        host = (p.hostname or "").lower().rstrip(".")
        port = p.port
        default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        netloc = host if not port or default else f"{host}:{port}"
        path = re.sub(r"/{2,}", "/", p.path or "/")
        return urlunsplit((scheme, netloc, path, p.query, ""))

    def make_source(self, url: str, content: str) -> NormalizedSource:
        canonical = self.normalize_url(url)
        domain = urlsplit(canonical).hostname or ""
        return NormalizedSource(canonical, canonical, domain,
                                hashlib.sha256(content.encode("utf-8", "replace")).hexdigest())

    def exact_span(self, document: str, quote: str, hint: int | None = None) -> tuple[int, int] | None:
        if hint is not None and document[hint:hint+len(quote)] == quote:
            return hint, hint+len(quote)
        idx = document.find(quote)
        return None if idx < 0 else (idx, idx+len(quote))
