from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit


def text_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def domain(url: str) -> str:
    return urlsplit(url).hostname or ""


class IndependenceAnalyzer:
    """Distinguishes distinct reporting from syndicated copies."""

    def independent_domains(self, urls: list[str]) -> set[str]:
        return {domain(u).removeprefix("www.") for u in urls}

    def likely_syndicated(self, snippets: list[str]) -> bool:
        if len(snippets) < 2:
            return False
        fps = {text_fingerprint(x) for x in snippets}
        return len(fps) < len(snippets)
