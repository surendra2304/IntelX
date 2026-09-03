"""INTELX Continuous Research Delta Engine for Subscriptions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Delta:
    """Calculated variance between successive research investigation snapshots."""

    new_sources: tuple[str, ...]
    new_claims: tuple[str, ...]
    changed_claims: tuple[str, ...]
    new_contradictions: tuple[str, ...] = ()
    resolved_contradictions: tuple[str, ...] = ()


class DeltaResearch:
    """Detects new, modified, or contradictory findings across continuous research runs."""

    def diff(
        self,
        prev_sources: set[str],
        curr_sources: set[str],
        prev_claims: set[str],
        curr_claims: set[str],
        prev_contradictions: set[str] | None = None,
        curr_contradictions: set[str] | None = None,
    ) -> Delta:
        """Compute delta between baseline and current state."""
        prev_cntr = prev_contradictions or set()
        curr_cntr = curr_contradictions or set()

        new_src = tuple(sorted(curr_sources - prev_sources))
        new_cl = tuple(sorted(curr_claims - prev_claims))
        new_cntr = tuple(sorted(curr_cntr - prev_cntr))
        res_cntr = tuple(sorted(prev_cntr - curr_cntr))

        return Delta(
            new_sources=new_src,
            new_claims=new_cl,
            changed_claims=(),
            new_contradictions=new_cntr,
            resolved_contradictions=res_cntr,
        )
