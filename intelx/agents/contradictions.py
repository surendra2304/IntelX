"""INTELX Cross-Source Contradiction and Semantic Conflict Engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from typing import Any


@dataclass(frozen=True, slots=True)
class Conflict:
    """Detected material conflict between two propositions or numerical measurements."""

    claim_a_id: str
    claim_b_id: str
    reason: str
    conflict_type: str = "factual"


_GENERIC_SUBJECTS = {"", "entity", "unknown", "system", "the system", "this", "it"}
_NUMBER = r"(?P<value>\d+(?:,\d{3})*(?:\.\d+)?)"
_MEASUREMENT_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "energy_density",
        "Wh/kg",
        re.compile(_NUMBER + r"\s*Wh\s*/\s*kg\b", re.IGNORECASE),
    ),
    (
        "conductivity",
        "mS/cm",
        re.compile(_NUMBER + r"\s*mS\s*/\s*cm\b", re.IGNORECASE),
    ),
    (
        "cycle_life",
        "cycles",
        re.compile(_NUMBER + r"\s*cycles?\b", re.IGNORECASE),
    ),
    (
        "temperature",
        "degrees Celsius",
        re.compile(_NUMBER + r"\s*(?:degrees?\s+Celsius|°C)\b", re.IGNORECASE),
    ),
    (
        "pressure",
        "MPa",
        re.compile(_NUMBER + r"\s*MPa\b", re.IGNORECASE),
    ),
    (
        "capacity_retention",
        "%",
        re.compile(_NUMBER + r"\s*%(?!\w)", re.IGNORECASE),
    ),
)


class ContradictionEngine:
    """Find same-subject conflicts while keeping unrelated metrics and sources separate."""

    def analyze(
        self,
        claims: list[Any],
        context_by_claim: dict[str, str] | None = None,
    ) -> list[Conflict]:
        """Examine claims for materially divergent measurements or explicit opposition."""
        contexts = context_by_claim or {}
        conflicts: list[Conflict] = []
        for claim_a, claim_b in combinations(claims, 2):
            text_a = self._claim_text(claim_a)
            text_b = self._claim_text(claim_b)
            subject_a = self._subject_key(
                claim_a, text_a, contexts.get(self._claim_id(claim_a), "")
            )
            subject_b = self._subject_key(
                claim_b, text_b, contexts.get(self._claim_id(claim_b), "")
            )
            if subject_a is None or subject_a != subject_b:
                continue

            measurement_a = self._measurement(text_a)
            measurement_b = self._measurement(text_b)
            if measurement_a and measurement_b:
                metric_a, unit_a, value_a = measurement_a
                metric_b, unit_b, value_b = measurement_b
                if metric_a == metric_b and unit_a == unit_b:
                    relative_difference = abs(value_a - value_b) / max(
                        abs(value_a), abs(value_b), 1e-9
                    )
                    if relative_difference > 0.10:
                        conflicts.append(
                            Conflict(
                                claim_a_id=self._claim_id(claim_a),
                                claim_b_id=self._claim_id(claim_b),
                                reason=(
                                    f"Conflicting {metric_a} measurements for {subject_a}: "
                                    f"{value_a:g} {unit_a} vs {value_b:g} {unit_b} "
                                    f"({relative_difference:.1%} difference)."
                                ),
                                conflict_type="measurement",
                            )
                        )
                    continue

            qualitative_reason = self._qualitative_conflict(text_a, text_b)
            if qualitative_reason:
                conflicts.append(
                    Conflict(
                        claim_a_id=self._claim_id(claim_a),
                        claim_b_id=self._claim_id(claim_b),
                        reason=qualitative_reason,
                        conflict_type="qualitative",
                    )
                )

        return conflicts

    @staticmethod
    def _get(claim: Any, name: str, default: Any = None) -> Any:
        if isinstance(claim, dict):
            return claim.get(name, default)
        return getattr(claim, name, default)

    @classmethod
    def _claim_id(cls, claim: Any) -> str:
        return str(cls._get(claim, "claim_id", cls._get(claim, "id", "")))

    @classmethod
    def _claim_text(cls, claim: Any) -> str:
        parts = [cls._get(claim, "text", ""), cls._get(claim, "quote", "")]
        return " ".join(str(part) for part in parts if part).strip()

    @classmethod
    def _subject_key(cls, claim: Any, text: str, context: str = "") -> str | None:
        """Resolve common domain subjects, preferring claim text over nearby context."""

        def classify(value: str) -> str | None:
            lowered = value.lower()
            if "silicon" in lowered and any(term in lowered for term in ("anode", "graphite")):
                return "silicon_anode"
            if "prussian blue" in lowered:
                return "prussian_blue_sodium_cathode"
            if "layered oxide" in lowered:
                return "layered_oxide_sodium_cathode"
            if any(term in lowered for term in ("sodium-ion", "sodium ion", "sodium cathode")):
                return "sodium_ion_battery"
            if any(
                term in lowered for term in ("solid-state", "solid state", "sulfide electrolyte")
            ):
                return "solid_state_battery"
            if any(
                term in lowered for term in ("quantum annealer", "quantum processing unit", "qpu")
            ):
                return "quantum_processor"
            return None

        subject_key = classify(text) or classify(context)
        if subject_key:
            return subject_key

        subject = cls._get(claim, "subject", "")
        if isinstance(subject, str):
            normalized = re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_")
            if normalized not in _GENERIC_SUBJECTS:
                return normalized
        entities = cls._get(claim, "entities_json", cls._get(claim, "entities", [])) or []
        if isinstance(entities, list):
            entity_names = [str(item).strip().lower() for item in entities if str(item).strip()]
            if len(entity_names) == 1 and entity_names[0] not in _GENERIC_SUBJECTS:
                return re.sub(r"[^a-z0-9]+", "_", entity_names[0]).strip("_")
        return None

    @staticmethod
    def _measurement(text: str) -> tuple[str, str, float] | None:
        """Extract one comparable measurement with a conservative metric family."""
        lowered = text.lower()
        for metric, unit, pattern in _MEASUREMENT_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            if metric == "capacity_retention" and not any(
                marker in lowered
                for marker in ("retention", "capacity", "efficiency", "degradation")
            ):
                continue
            value = float(match.group("value").replace(",", ""))
            if not (value >= 0.0 and value < float("inf")):
                continue
            return metric, unit, value
        return None

    @staticmethod
    def _qualitative_conflict(text_a: str, text_b: str) -> str | None:
        """Return a reason for clear opposing language on an already-matched subject."""
        a = text_a.lower()
        b = text_b.lower()
        opposing_pairs = (
            (("increases", "decreases"), "opposing directional assertions (increase vs decrease)"),
            (
                ("increased", "decreased"),
                "opposing directional assertions (increased vs decreased)",
            ),
            (("rises", "falls"), "opposing directional assertions (rise vs fall)"),
            (("fails", "succeeds"), "contradictory outcome assertion (fails vs succeeds)"),
        )
        for (left, right), reason in opposing_pairs:
            if (left in a and right in b) or (right in a and left in b):
                return reason
        a_is_negative = " not " in f" {a} "
        b_is_negative = " not " in f" {b} "
        if a_is_negative != b_is_negative:
            negative_text, affirmative_text = (a, b) if a_is_negative else (b, a)
            negated_terms = {
                token
                for token in re.findall(r"\b[a-z]{5,}\b", negative_text)
                if token not in {"there", "which", "their", "these", "those", "about"}
            }
            affirmed_terms = set(re.findall(r"\b[a-z]{5,}\b", affirmative_text))
            if negated_terms & affirmed_terms:
                return "direct negation of a shared proposition"
        return None
