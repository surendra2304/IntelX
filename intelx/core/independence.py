"""INTELX Evidence Independence Evaluation and N-Gram Overlap Analysis."""

import re
from typing import Any

from intelx.db.models import Document, Source


def compute_3gram_jaccard(text_a: str, text_b: str) -> float:
    """Compute character 3-gram Jaccard similarity between two text snippets."""
    clean_a = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text_a.lower())).strip()
    clean_b = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text_b.lower())).strip()

    if not clean_a or not clean_b:
        return 0.0

    if len(clean_a) < 3 or len(clean_b) < 3:
        return 1.0 if clean_a == clean_b else 0.0

    grams_a = {clean_a[i : i + 3] for i in range(len(clean_a) - 2)}
    grams_b = {clean_b[i : i + 3] for i in range(len(clean_b) - 2)}

    intersection = len(grams_a & grams_b)
    union = len(grams_a | grams_b)

    return intersection / union if union > 0 else 0.0


def _extract_field(obj: Any, field_name: str) -> str:
    """Safely extract string field value from ORM model or dict."""
    if isinstance(obj, dict):
        return (obj.get(field_name) or "").strip().lower()
    return (getattr(obj, field_name, None) or "").strip().lower()


def is_independent_evidence(
    source_a: Source | dict[str, Any],
    doc_a: Document | dict[str, Any] | None,
    quote_a: str,
    source_b: Source | dict[str, Any],
    doc_b: Document | dict[str, Any] | None,
    quote_b: str,
) -> tuple[bool, str]:
    """Determine whether two evidence items originate from genuinely independent sources."""
    domain_a = _extract_field(source_a, "domain")
    domain_b = _extract_field(source_b, "domain")

    # Rule 1: Different registered domains
    if domain_a and domain_b and domain_a == domain_b:
        return False, f"Same domain '{domain_a}'"

    # Rule 2: Different publisher
    pub_a = _extract_field(source_a, "publisher")
    pub_b = _extract_field(source_b, "publisher")
    if pub_a and pub_b and pub_a == pub_b:
        return False, f"Same publisher '{pub_a}'"

    # Rule 3: Different document fingerprints
    fp_a = _extract_field(source_a, "fingerprint")
    fp_b = _extract_field(source_b, "fingerprint")
    if fp_a and fp_b and fp_a == fp_b:
        return False, "Identical document fingerprint"

    # Rule 4: 3-gram Jaccard overlap < 0.50 (filter wire/syndicated duplicates)
    jaccard = compute_3gram_jaccard(quote_a, quote_b)
    if jaccard >= 0.50:
        return False, f"Syndicated overlap detected (3-gram Jaccard {jaccard:.2f} >= 0.50)"

    return True, "Genuinely independent sources"
