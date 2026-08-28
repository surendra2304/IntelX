"""INTELX Ingestion Sanitizer and Prompt Injection Risk Scanner."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INJECTION_PATTERNS = [
    r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b",
    r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior|above)\b",
    r"(?i)\byou\s+are\s+now\b",
    r"(?i)\bsystem\s*:\s*",
    r"(?i)\b\[system\]\b",
    r"(?i)\b\[inst\]|\[\/inst\]\b",
    r"<\|im_start\|>|<\|im_end\|>|<\|system\|>|<\|user\|>|<\|assistant\|>",
    r"(?i)\bforget\s+all\s+(?:previous\s+)?instructions\b",
    r"(?i)\boverride\s+(?:all\s+)?system\s+prompt\b",
    r"(?i)\bjailbreak\b",
    r"(?i)\byou\s+are\s+an?\s+unrestricted\b",
    r"(?i)<!--\s*(?:instructions|prompt|system|override|ignore).*?-->",
    r"(?i)<\/?(?:system|instructions|prompt|assistant|human|context)>",
    r"(?i)\bprint\s+(?:your\s+)?(?:entire\s+)?system\s+prompt\b",
    r"(?i)<<<END_EXTERNAL_DOCUMENT>>>|<<<EXTERNAL_DOCUMENT",
    r"""(?i)["']role["']\s*:\s*["']system["']""",
    r"(?i)javascript:\s*alert",
]

# Homoglyph translation mapping for common evasion tricks (Cyrillic to Latin)
HOMOGLYPH_MAP = str.maketrans(
    {
        "а": "a",
        "с": "c",
        "е": "e",
        "о": "o",
        "р": "p",
        "ѕ": "s",
        "х": "x",
        "у": "y",
        "і": "i",
        "А": "A",
        "С": "C",
        "Е": "E",
        "О": "O",
        "Р": "P",
        "Ѕ": "S",
        "Х": "X",
        "У": "Y",
        "І": "I",
    }
)


@dataclass
class ScanResult:
    """Outcome of prompt injection scan."""

    injection_risk: bool
    flags_count: int
    matches: list[dict[str, Any]]


class IngestionSanitizer:
    """Non-mutating prompt injection scanner preserving exact text offsets."""

    def __init__(self, raw_storage_dir: Path | None = None) -> None:
        self.raw_storage_dir = raw_storage_dir or Path("./data/raw").resolve()

    def scan(self, text: str, fingerprint: str | None = None) -> ScanResult:
        """Scan normalized text for injection signatures without altering a single character."""
        matches: list[dict[str, Any]] = []

        # Standard check
        for pattern in INJECTION_PATTERNS:
            for m in re.finditer(pattern, text):
                matches.append(
                    {
                        "pattern": pattern,
                        "span_start": m.start(),
                        "span_end": m.end(),
                        "matched_text": m.group(0),
                    }
                )

        # Homoglyph & Unicode normalized check
        normalized_homoglyphs = text.translate(HOMOGLYPH_MAP)
        if normalized_homoglyphs != text:
            for pattern in INJECTION_PATTERNS:
                for m in re.finditer(pattern, normalized_homoglyphs):
                    matches.append(
                        {
                            "pattern": f"homoglyph:{pattern}",
                            "span_start": m.start(),
                            "span_end": m.end(),
                            "matched_text": m.group(0),
                        }
                    )

        has_risk = len(matches) > 0

        if has_risk and fingerprint:
            self._persist_flags_sidecar(fingerprint, matches)

        return ScanResult(
            injection_risk=has_risk,
            flags_count=len(matches),
            matches=matches,
        )

    def _persist_flags_sidecar(self, fingerprint: str, matches: list[dict[str, Any]]) -> None:
        """Save injection findings to a sidecar JSON file."""
        try:
            self.raw_storage_dir.mkdir(parents=True, exist_ok=True)
            flags_file = self.raw_storage_dir / f"{fingerprint}.flags.json"
            flags_file.write_text(
                json.dumps({"fingerprint": fingerprint, "flags": matches}, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Could not persist sidecar flags for {fingerprint}: {e}")
