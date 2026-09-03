"""INTELX Untrusted External Context Firewall and Prompt Injection Boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextPiece:
    """Delimited unit of contextual information with explicit trust boundary tagging."""

    text: str
    trusted: bool
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class FirewallResult:
    """Result of context inspection separating trusted instructions from untrusted data."""

    pieces: tuple[ContextPiece, ...]
    injection_signals: tuple[str, ...]


class ContextFirewall:
    """Isolates untrusted external documents, search snippets, and data from LLM system prompts."""

    patterns: list[tuple[str, str]] = [
        ("ignore_previous", r"ignore\s+(?:all\s+)?previous\s+instructions"),
        ("system_prompt", r"reveal\s+(?:the\s+)?system\s+prompt"),
        ("override_policy", r"override\s+(?:the\s+)?policy"),
        ("disable_guardrails", r"disable\s+(?:all\s+)?guardrails"),
        ("secret_exfiltration", r"(?:print|output|dump)\s+(?:all\s+)?(?:env|keys|credentials|secrets)"),
    ]

    def inspect(self, trusted: str, external: str, source_id: str | None = None) -> FirewallResult:
        """Inspect external content for adversarial injection signals and wrap in trust boundary."""
        signals = tuple(name for name, pat in self.patterns if re.search(pat, external, re.I))
        pieces = (
            ContextPiece(trusted, True),
            ContextPiece(external, False, source_id),
        )
        return FirewallResult(pieces=pieces, injection_signals=signals)
