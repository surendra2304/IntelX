"""INTELX Entity Resolution and Deduplication Engine."""

import difflib
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import EntityMergeStatus, EntityType
from intelx.db.models import Entity, EntityAlias, EntityMerge

logger = logging.getLogger(__name__)

STOP_SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|co|company|group)\b", re.IGNORECASE
)


def normalize_entity_name(name: str) -> str:
    """Normalize entity name for canonical indexing (lowercase, strip symbols, collapse spaces)."""
    cleaned = re.sub(r"[^\w\s]", "", name.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def compute_entity_similarity(name_a: str, name_b: str) -> float:
    """Compute string similarity score between two entity names with suffix awareness."""
    norm_a = normalize_entity_name(name_a)
    norm_b = normalize_entity_name(name_b)

    if not norm_a or not norm_b:
        return 0.0

    if norm_a == norm_b:
        return 1.0

    # Clean corporate/organizational suffixes for base comparison
    base_a = re.sub(r"\s+", " ", STOP_SUFFIXES.sub("", norm_a)).strip()
    base_b = re.sub(r"\s+", " ", STOP_SUFFIXES.sub("", norm_b)).strip()

    if base_a and base_b and base_a == base_b:
        return 0.98

    seq_ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    union = tokens_a | tokens_b
    token_jaccard = len(tokens_a & tokens_b) / len(union) if union else 0.0

    return max(seq_ratio, token_jaccard)


class EntityResolver:
    """Deterministic entity resolver with alias indexing and automated merge proposals."""

    @classmethod
    async def resolve_or_create(
        cls,
        session: AsyncSession,
        name: str,
        entity_type: EntityType = EntityType.OTHER,
        aliases: list[str] | None = None,
        run_id: str | None = None,
    ) -> tuple[Entity, EntityMergeStatus | None]:
        """Resolve entity by exact name, alias index, or similarity thresholds."""
        canonical_name = name.strip()

        # 1. Exact canonical name match
        stmt_exact = select(Entity).where(Entity.canonical_name == canonical_name)
        existing_entity = (await session.execute(stmt_exact)).scalar_one_or_none()
        if existing_entity:
            if aliases:
                await cls._add_aliases(session, existing_entity.id, aliases)
            return existing_entity, None

        # 2. Match via EntityAlias table
        stmt_alias = select(EntityAlias).where(EntityAlias.alias == canonical_name)
        alias_record = (await session.execute(stmt_alias)).scalar_one_or_none()
        if alias_record:
            stmt_parent = select(Entity).where(Entity.id == alias_record.entity_id)
            parent_entity = (await session.execute(stmt_parent)).scalar_one_or_none()
            if parent_entity:
                return parent_entity, EntityMergeStatus.APPLIED

        # 3. Fuzzy similarity matching against existing entities of same type
        stmt_all = select(Entity).where(Entity.type == entity_type)
        candidates = list((await session.execute(stmt_all)).scalars().all())

        best_match: Entity | None = None
        best_score = 0.0

        for cand in candidates:
            score = compute_entity_similarity(canonical_name, cand.canonical_name)
            if score > best_score:
                best_score = score
                best_match = cand

        # Case A: High confidence near-match (score >= 0.95) -> Auto-apply merge
        if best_match and best_score >= 0.95:
            logger.info(
                f"Auto-merging '{canonical_name}' -> '{best_match.canonical_name}' "
                f"({best_score:.2f})"
            )
            new_ent = Entity(
                canonical_name=canonical_name,
                type=entity_type,
                created_by_run_id=run_id,
            )
            session.add(new_ent)
            await session.flush()

            merge_record = EntityMerge(
                kept_entity_id=best_match.id,
                merged_entity_id=new_ent.id,
                score=best_score,
                status=EntityMergeStatus.APPLIED,
            )
            session.add(merge_record)
            await cls._add_aliases(session, best_match.id, [canonical_name] + (aliases or []))
            await session.flush()
            return best_match, EntityMergeStatus.APPLIED

        # Create the new distinct entity first
        new_entity = Entity(
            canonical_name=canonical_name,
            type=entity_type,
            created_by_run_id=run_id,
        )
        session.add(new_entity)
        await session.flush()

        if aliases:
            await cls._add_aliases(session, new_entity.id, aliases)

        # Case B: Moderate similarity (0.70 <= score < 0.95) -> Create PROPOSED merge
        if best_match and best_score >= 0.70:
            logger.info(
                f"Proposing merge '{new_entity.canonical_name}' and '{best_match.canonical_name}' "
                f"({best_score:.2f})"
            )
            merge_proposal = EntityMerge(
                kept_entity_id=best_match.id,
                merged_entity_id=new_entity.id,
                score=best_score,
                status=EntityMergeStatus.PROPOSED,
            )
            session.add(merge_proposal)
            await session.flush()
            return new_entity, EntityMergeStatus.PROPOSED

        # Case C: Distinct entity (score < 0.70)
        return new_entity, None

    @staticmethod
    async def _add_aliases(session: AsyncSession, entity_id: str, aliases: list[str]) -> None:
        """Add unique aliases to entity without duplication."""
        for alias in aliases:
            cleaned = alias.strip()
            if not cleaned:
                continue
            stmt = select(EntityAlias).where(
                EntityAlias.entity_id == entity_id,
                EntityAlias.alias == cleaned,
            )
            exists = (await session.execute(stmt)).scalar_one_or_none()
            if not exists:
                session.add(EntityAlias(entity_id=entity_id, alias=cleaned))
        await session.flush()
