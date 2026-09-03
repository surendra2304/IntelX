from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ContextPiece:
    text: str
    trusted: bool
    source_id: str | None = None

@dataclass(frozen=True, slots=True)
class FirewallResult:
    pieces: tuple[ContextPiece,...]
    injection_signals: tuple[str,...]

class ContextFirewall:
    patterns = [
        ("ignore_previous", r"ignore\s+(?:all\s+)?previous\s+instructions"),
        ("system_prompt", r"reveal\s+(?:the\s+)?system\s+prompt"),
        ("override_policy", r"override\s+(?:the\s+)?policy"),
        ("disable_guardrails", r"disable\s+(?:all\s+)?guardrails"),
    ]
    def inspect(self, trusted: str, external: str, source_id: str | None=None) -> FirewallResult:
        signals = tuple(name for name, pat in self.patterns if re.search(pat, external, re.I))
        return FirewallResult((ContextPiece(trusted, True), ContextPiece(external, False, source_id)), signals)
