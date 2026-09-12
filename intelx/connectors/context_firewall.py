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

    @property
    def injection_detected(self) -> bool:
        return len(self.injection_signals) > 0


class ContextFirewall:
    """Isolates untrusted external documents, search snippets, and data from LLM system prompts."""

    patterns: list[tuple[str, str]] = [
        ("ignore_previous", r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b"),
        ("disregard_instructions", r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior|above)\b"),
        ("system_prompt", r"(?i)\b(?:reveal|print|output|dump)\s+(?:the\s+|your\s+)?(?:entire\s+)?system\s+prompt\b"),
        ("override_policy", r"(?i)\boverride\s+(?:the\s+|all\s+)?(?:system\s+)?policy\b"),
        ("disable_guardrails", r"(?i)\bdisable\s+(?:all\s+)?guardrails\b"),
        ("secret_exfiltration", r"(?i)\b(?:print|output|dump)\s+(?:all\s+)?(?:env|keys|credentials|secrets)\b"),
        ("role_impersonation", r"(?i)(?:\b\[system\]\b|\bsystem\s*:|<\|system\|>|<\|im_start\|>|<\|im_end\|>)"),
        ("instruction_tag", r"(?i)(?:\[inst\]|\[\/inst\]|<\/?(?:instructions|prompt|assistant|human)>)"),
        ("delimiter_breakout", r"(?i)(?:<<<END_EXTERNAL_DOCUMENT>>>|<<<EXTERNAL_DOCUMENT|<\/untrusted_external_content>)"),
        ("jailbreak", r"(?i)\b(?:jailbreak|you\s+are\s+now\s+an?\s+unrestricted|DAN\s+mode)\b"),
    ]

    def inspect(self, trusted: str, external: str, source_id: str | None = None) -> FirewallResult:
        """Inspect external content for adversarial injection signals and wrap in trust boundary."""
        signals = tuple(name for name, pat in self.patterns if re.search(pat, external, re.I))
        pieces = (
            ContextPiece(trusted, True),
            ContextPiece(external, False, source_id),
        )
        return FirewallResult(pieces=pieces, injection_signals=signals)

    def sanitize(self, external: str, source_id: str | None = None) -> str:
        """Sanitize untrusted content by escaping delimiter markers and neutralizing hostile directives."""
        if not external:
            return ""

        sanitized = external

        # 1. Neutralize delimiter breakout attempts
        sanitized = re.sub(
            r"(?i)<<<END_EXTERNAL_DOCUMENT>>>",
            "[ESCAPED_DELIMITER_END]",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)<<<EXTERNAL_DOCUMENT",
            "[ESCAPED_DELIMITER_START",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)<\/untrusted_external_content>",
            "[ESCAPED_UNTRUSTED_TAG]",
            sanitized,
        )

        # 2. Neutralize role impersonation / instruction tags
        sanitized = re.sub(
            r"(?i)<\|im_start\|>|<\|im_end\|>|<\|system\|>|<\|user\|>|<\|assistant\|>",
            "[NEUTRALIZED_SPECIAL_TOKEN]",
            sanitized,
        )
        sanitized = re.sub(
            r"(?i)\[inst\]|\[\/inst\]",
            "[NEUTRALIZED_INST]",
            sanitized,
        )

        # 3. Neutralize direct override commands by prefixing with inert marker
        for name, pat in self.patterns:
            if name in ("ignore_previous", "disregard_instructions", "override_policy", "disable_guardrails", "system_prompt"):
                def _neutralize(m: re.Match) -> str:
                    return f"[INERT_HOSTILE_DIRECTIVE: {m.group(0)}]"
                sanitized = re.sub(pat, _neutralize, sanitized)

        return sanitized
