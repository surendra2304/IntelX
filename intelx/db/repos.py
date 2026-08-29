"""INTELX Repository Layer with Typed CRUD, Integrity Checks, and Audit Verification."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import (
    ClaimOrigin,
    ClaimStatus,
    ClaimType,
    EvidenceSupportType,
    RunOutcome,
    RunStatus,
    SourceKind,
    TrustTier,
)
from intelx.core.errors import IntegrityError, NotFoundError
from intelx.core.settings import get_settings
from intelx.db.models import (
    AuditEvent,
    Chunk,
    Claim,
    Document,
    Event,
    Evidence,
    ResearchRun,
    Source,
)


def canonical_json(data: Any) -> str:
    """Serialize dictionary/structure into canonical sorted JSON string."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_sha256(content: str) -> str:
    """Compute standard SHA256 hex digest for a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class RunRepo:
    """Repository managing research run state, budgeting, and event logs."""

    @staticmethod
    async def create_run(
        session: AsyncSession,
        objective: str,
        scope_json: dict[str, Any] | None = None,
        created_by: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResearchRun:
        """Create a new research run in QUEUED status."""
        run = ResearchRun(
            objective=objective,
            scope_json=scope_json or {},
            status=RunStatus.QUEUED,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        session.add(run)
        await session.flush()
        return run

    @staticmethod
    async def get_run(session: AsyncSession, run_id: str) -> ResearchRun | None:
        """Retrieve research run by ID."""
        stmt = select(ResearchRun).where(ResearchRun.id == run_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_claim_next_queued_job(
        session: AsyncSession, max_concurrent: int | None = None
    ) -> ResearchRun | None:
        """Atomically claim the next queued research job with priority handling and concurrency bounds."""
        settings = get_settings()
        limit = max_concurrent if max_concurrent is not None else settings.MAX_CONCURRENT_RUNS

        active_statuses = [
            RunStatus.PLANNING,
            RunStatus.DISCOVERING,
            RunStatus.RETRIEVING,
            RunStatus.EXTRACTING,
            RunStatus.VERIFYING,
            RunStatus.ANALYZING,
            RunStatus.SYNTHESIZING,
            RunStatus.REVIEW_REQUIRED,
        ]
        stmt_active = select(func.count(ResearchRun.id)).where(
            ResearchRun.status.in_(active_statuses)
        )
        active_count = (await session.execute(stmt_active)).scalar_one() or 0
        if active_count >= limit:
            return None

        priority_order = case(
            (func.json_extract(ResearchRun.scope_json, "$.priority") == "urgent", 0),
            (func.json_extract(ResearchRun.scope_json, "$.context.priority") == "urgent", 0),
            (func.json_extract(ResearchRun.scope_json, "$.priority") == "high", 1),
            (func.json_extract(ResearchRun.scope_json, "$.context.priority") == "high", 1),
            else_=2,
        )
        stmt = (
            select(ResearchRun)
            .where(ResearchRun.status == RunStatus.QUEUED)
            .order_by(priority_order.asc(), ResearchRun.created_at.asc())
            .limit(1)
        )
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            return None

        run.status = RunStatus.PLANNING
        run.started_at = datetime.now(UTC)
        await session.flush()
        return run

    @classmethod
    async def claim_next_queued_run(cls, session: AsyncSession) -> ResearchRun | None:
        """Alias for claiming the next queued job."""
        return await cls.get_or_claim_next_queued_job(session)

    @staticmethod
    async def set_status(
        session: AsyncSession,
        run_id: str,
        status: RunStatus,
        outcome: RunOutcome | None = None,
        error_json: dict[str, Any] | None = None,
    ) -> ResearchRun:
        """Update run status, outcome, and error metadata."""
        run = await RunRepo.get_run(session, run_id)
        if not run:
            raise NotFoundError(f"Run {run_id} not found")
        run.status = status
        if outcome is not None:
            run.outcome = outcome
        if error_json is not None:
            run.error_json = error_json
        if status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            run.completed_at = datetime.now(UTC)
        await session.flush()
        return run

    @classmethod
    async def update_status(
        cls,
        session: AsyncSession,
        run_id: str,
        status: RunStatus,
        outcome: RunOutcome | None = None,
        error_json: dict[str, Any] | None = None,
    ) -> ResearchRun:
        """Alias for set_status."""
        return await cls.set_status(session, run_id, status, outcome, error_json)

    @staticmethod
    async def update_cost_counters(
        session: AsyncSession,
        run_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        usd_cost: float = 0.0,
        tool_calls: int = 0,
    ) -> ResearchRun:
        """Incrementally update resource and financial cost counters for a run."""
        stmt = (
            update(ResearchRun)
            .where(ResearchRun.id == run_id)
            .values(
                input_tokens=ResearchRun.input_tokens + input_tokens,
                output_tokens=ResearchRun.output_tokens + output_tokens,
                usd_cost=ResearchRun.usd_cost + usd_cost,
                tool_calls=ResearchRun.tool_calls + tool_calls,
            )
        )
        await session.execute(stmt)
        await session.flush()
        run = await RunRepo.get_run(session, run_id)
        if not run:
            raise NotFoundError(f"Run {run_id} not found")
        return run

    @staticmethod
    async def add_event(
        session: AsyncSession,
        run_id: str,
        event_type: str,
        payload_json: dict[str, Any] | None = None,
    ) -> Event:
        """Append an operational event to the run's audit stream."""
        event = Event(
            run_id=run_id,
            type=event_type,
            payload_json=payload_json or {},
        )
        session.add(event)
        await session.flush()
        return event

    @staticmethod
    async def get_events_for_run(session: AsyncSession, run_id: str) -> list[Event]:
        """Fetch all chronological events for a given research run."""
        stmt = select(Event).where(Event.run_id == run_id).order_by(Event.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())


class SourceRepo:
    """Repository managing external sources, normalized documents, and text chunks."""

    @staticmethod
    async def create_source(
        session: AsyncSession,
        kind: SourceKind,
        location: str,
        domain: str | None = None,
        publisher: str | None = None,
        title: str | None = None,
        published_at: datetime | None = None,
        content_type: str = "text/html",
        fingerprint: str | None = None,
        trust_tier: TrustTier | None = None,
        robots_ok: bool = True,
        license_note: str | None = None,
        injection_risk: bool = False,
        raw_path: str | None = None,
        created_by_run_id: str | None = None,
    ) -> Source:
        """Create a new external source record."""
        computed_fingerprint = fingerprint or compute_sha256(location)
        default_tier = TrustTier.STANDARD if kind == SourceKind.FILE else TrustTier.QUARANTINE
        source = Source(
            kind=kind,
            location=location,
            domain=domain,
            publisher=publisher,
            title=title,
            published_at=published_at,
            content_type=content_type,
            fingerprint=computed_fingerprint,
            trust_tier=trust_tier or default_tier,
            robots_ok=robots_ok,
            license_note=license_note,
            injection_risk=injection_risk,
            raw_path=raw_path,
            created_by_run_id=created_by_run_id,
        )
        session.add(source)
        await session.flush()
        return source

    @staticmethod
    async def get_source_by_fingerprint(session: AsyncSession, fingerprint: str) -> Source | None:
        """Find source by its SHA256 content fingerprint for deduplication."""
        stmt = select(Source).where(Source.fingerprint == fingerprint)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create_source(
        session: AsyncSession,
        kind: SourceKind,
        location: str,
        fingerprint: str,
        **kwargs: Any,
    ) -> tuple[Source, bool]:
        """Atomically find existing source by fingerprint or create a new one."""
        existing = await SourceRepo.get_source_by_fingerprint(session, fingerprint)
        if existing:
            return existing, False
        new_source = await SourceRepo.create_source(
            session=session,
            kind=kind,
            location=location,
            fingerprint=fingerprint,
            **kwargs,
        )
        return new_source, True

    @staticmethod
    async def get_source(session: AsyncSession, source_id: str) -> Source | None:
        """Fetch source by ID."""
        stmt = select(Source).where(Source.id == source_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def set_trust(session: AsyncSession, source_id: str, trust_tier: TrustTier) -> Source:
        """Update the trust tier for a source."""
        source = await SourceRepo.get_source(session, source_id)
        if not source:
            raise NotFoundError(f"Source {source_id} not found")
        source.trust_tier = trust_tier
        await session.flush()
        return source

    @staticmethod
    async def get_sources_by_tier(session: AsyncSession, trust_tier: TrustTier) -> list[Source]:
        """Fetch all sources belonging to a specific trust tier."""
        stmt = select(Source).where(Source.trust_tier == trust_tier)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_document(
        session: AsyncSession,
        source_id: str,
        text_content: str,
        language: str = "en",
        version: int = 1,
    ) -> Document:
        """Create a normalized textual document associated with a source."""
        doc = Document(
            source_id=source_id,
            text=text_content,
            language=language,
            version=version,
        )
        session.add(doc)
        await session.flush()
        return doc

    @staticmethod
    async def get_document(session: AsyncSession, document_id: str) -> Document | None:
        """Fetch document by primary key."""
        stmt = select(Document).where(Document.id == document_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_document_by_source_id(session: AsyncSession, source_id: str) -> Document | None:
        """Fetch primary document associated with a source."""
        stmt = (
            select(Document)
            .where(Document.source_id == source_id)
            .order_by(Document.version.desc())
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_chunk(
        session: AsyncSession,
        document_id: str,
        idx: int,
        start_char: int,
        end_char: int,
        text_content: str,
    ) -> Chunk:
        """Create an indexed chunk with absolute character offsets into document text."""
        chunk = Chunk(
            document_id=document_id,
            idx=idx,
            start_char=start_char,
            end_char=end_char,
            text=text_content,
        )
        session.add(chunk)
        await session.flush()
        return chunk

    @staticmethod
    async def get_chunk(session: AsyncSession, chunk_id: str) -> Chunk | None:
        """Fetch chunk by ID."""
        stmt = select(Chunk).where(Chunk.id == chunk_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class ClaimRepo:
    """Repository managing verifiable claims with span integrity checks and FTS search."""

    @staticmethod
    async def create_claim(
        session: AsyncSession,
        run_id: str,
        source_id: str,
        document_id: str,
        chunk_id: str,
        text_content: str,
        quote: str,
        span_start: int,
        span_end: int,
        claim_type: ClaimType,
        subject: str | None = None,
        predicate: str | None = None,
        object_val: str | None = None,
        entities_json: list[str] | None = None,
        confidence: float = 1.0,
        confidence_method: str = "v1-composite",
        origin: ClaimOrigin = ClaimOrigin.EXTRACTED,
        status: ClaimStatus = ClaimStatus.ACTIVE,
        created_by_agent: str = "extractor",
    ) -> Claim:
        """Create a claim enforcing that verbatim quote matches exact document slice."""
        doc = await SourceRepo.get_document(session, document_id)
        if not doc:
            raise NotFoundError(f"Document {document_id} not found for claim verification")

        # Invariant Verification Rule: quote == doc.text[span_start:span_end]
        actual_slice = doc.text[span_start:span_end]
        if quote != actual_slice:
            raise IntegrityError(
                f"Claim span verification failed: quote '{quote}' != "
                f"document text slice '{actual_slice}' [{span_start}:{span_end}]"
            )

        claim = Claim(
            run_id=run_id,
            source_id=source_id,
            document_id=document_id,
            chunk_id=chunk_id,
            text=text_content,
            subject=subject,
            predicate=predicate,
            object=object_val,
            claim_type=claim_type,
            entities_json=entities_json or [],
            quote=quote,
            span_start=span_start,
            span_end=span_end,
            confidence=confidence,
            confidence_method=confidence_method,
            origin=origin,
            status=status,
            created_by_agent=created_by_agent,
        )
        session.add(claim)
        await session.flush()
        return claim

    @staticmethod
    async def get_claim(session: AsyncSession, claim_id: str) -> Claim | None:
        """Fetch claim by ID."""
        stmt = select(Claim).where(Claim.id == claim_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_claims_by_run(session: AsyncSession, run_id: str) -> list[Claim]:
        """Fetch all claims extracted for a specific research run."""
        stmt = select(Claim).where(Claim.run_id == run_id).order_by(Claim.created_at.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_claims_by_status(
        session: AsyncSession, run_id: str, status: ClaimStatus
    ) -> list[Claim]:
        """Fetch claims for a run matching a specific lifecycle status."""
        stmt = (
            select(Claim)
            .where(Claim.run_id == run_id, Claim.status == status)
            .order_by(Claim.created_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def search_claims_fts(session: AsyncSession, search_query: str) -> list[Claim]:
        """Search claims using FTS5 match where available, falling back to LIKE query."""
        try:
            raw_stmt = text(
                "SELECT claims.* FROM claims "
                "JOIN claims_fts ON claims.id = claims_fts.id "
                "WHERE claims_fts MATCH :query"
            )
            result = await session.execute(raw_stmt, {"query": search_query})
            claim_ids = [row.id for row in result.fetchall()]
            if claim_ids:
                stmt = select(Claim).where(Claim.id.in_(claim_ids))
                res = await session.execute(stmt)
                return list(res.scalars().all())
        except Exception:
            # Fallback to standard substring search if FTS5 is not available
            pass

        stmt = select(Claim).where(Claim.text.ilike(f"%{search_query}%"))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def search_chunks_fts(session: AsyncSession, search_query: str) -> list[Chunk]:
        """Search text chunks using FTS5 match where available, falling back to LIKE query."""
        try:
            raw_stmt = text(
                "SELECT chunks.* FROM chunks "
                "JOIN chunks_fts ON chunks.id = chunks_fts.id "
                "WHERE chunks_fts MATCH :query"
            )
            result = await session.execute(raw_stmt, {"query": search_query})
            chunk_ids = [row.id for row in result.fetchall()]
            if chunk_ids:
                stmt = select(Chunk).where(Chunk.id.in_(chunk_ids))
                res = await session.execute(stmt)
                return list(res.scalars().all())
        except Exception:
            # Fallback to substring query
            pass

        stmt = select(Chunk).where(Chunk.text.ilike(f"%{search_query}%"))
        result = await session.execute(stmt)
        return list(result.scalars().all())


class EvidenceRepo:
    """Repository managing granular supporting/contradicting evidence items."""

    @staticmethod
    async def create_evidence(
        session: AsyncSession,
        claim_id: str,
        source_id: str,
        document_id: str,
        chunk_id: str,
        span_start: int,
        span_end: int,
        quote: str,
        support_type: EvidenceSupportType,
        created_by_run_id: str,
        created_by_agent: str,
        independent_of_json: list[str] | None = None,
    ) -> Evidence:
        """Create evidence record with strict span verification."""
        doc = await SourceRepo.get_document(session, document_id)
        if not doc:
            raise NotFoundError(f"Document {document_id} not found for evidence verification")

        actual_slice = doc.text[span_start:span_end]
        if quote != actual_slice:
            raise IntegrityError(
                f"Evidence span verification failed: quote '{quote}' != "
                f"document text slice '{actual_slice}' [{span_start}:{span_end}]"
            )

        ev = Evidence(
            claim_id=claim_id,
            source_id=source_id,
            document_id=document_id,
            chunk_id=chunk_id,
            span_start=span_start,
            span_end=span_end,
            quote=quote,
            support_type=support_type,
            independent_of_json=independent_of_json or [],
            created_by_run_id=created_by_run_id,
            created_by_agent=created_by_agent,
        )
        session.add(ev)
        await session.flush()
        return ev

    @staticmethod
    async def get_evidence_for_claim(session: AsyncSession, claim_id: str) -> list[Evidence]:
        """Fetch all evidence items attached to a specific claim."""
        stmt = (
            select(Evidence)
            .where(Evidence.claim_id == claim_id)
            .order_by(Evidence.created_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class AuditChain:
    """Cryptographic append-only audit trail with tamper verification."""

    GENESIS_HASH = "0" * 64

    @staticmethod
    def _format_ts(ts: datetime | str) -> str:
        """Format timestamp consistently across database backends."""
        if isinstance(ts, str):
            return ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.isoformat()

    @classmethod
    def compute_record_hash(
        cls,
        prev_hash: str,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        detail_json: dict[str, Any],
        ts: datetime | str,
    ) -> str:
        """Compute SHA256 digest: sha256(prev_hash + canonical json of row)."""
        row_dict = {
            "actor": actor,
            "action": action,
            "object_type": object_type,
            "object_id": str(object_id),
            "detail_json": detail_json,
            "ts": cls._format_ts(ts),
        }
        payload = f"{prev_hash}{canonical_json(row_dict)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    async def append_event(
        cls,
        session: AsyncSession,
        actor: str,
        action: str,
        object_type: str,
        object_id: str,
        detail_json: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Append an audit record to the cryptographic hash chain."""
        # Query the latest audit event to find previous hash
        stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)
        res = await session.execute(stmt)
        latest = res.scalar_one_or_none()
        prev_hash = latest.hash if latest else cls.GENESIS_HASH

        ts = datetime.now(UTC)
        record_hash = cls.compute_record_hash(
            prev_hash=prev_hash,
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            detail_json=detail_json or {},
            ts=ts,
        )

        audit_entry = AuditEvent(
            ts=ts,
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            detail_json=detail_json or {},
            prev_hash=prev_hash,
            hash=record_hash,
        )
        session.add(audit_entry)
        await session.flush()
        return audit_entry

    @classmethod
    async def verify(cls, session: AsyncSession) -> tuple[bool, list[str]]:
        """Walk the entire audit ledger from beginning to end to detect any tampering."""
        stmt = select(AuditEvent).order_by(AuditEvent.id.asc())
        res = await session.execute(stmt)
        events = list(res.scalars().all())

        if not events:
            return True, []

        expected_prev_hash = cls.GENESIS_HASH
        errors: list[str] = []

        for entry in events:
            # 1. Verify prev_hash linkage
            if entry.prev_hash != expected_prev_hash:
                errors.append(
                    f"Broken hash link at audit event id={entry.id}: "
                    f"expected prev_hash {expected_prev_hash}, found {entry.prev_hash}"
                )

            # 2. Recompute record hash
            recomputed = cls.compute_record_hash(
                prev_hash=entry.prev_hash,
                actor=entry.actor,
                action=entry.action,
                object_type=entry.object_type,
                object_id=entry.object_id,
                detail_json=entry.detail_json,
                ts=entry.ts,
            )

            if recomputed != entry.hash:
                errors.append(
                    f"Tampered record at audit event id={entry.id}: "
                    f"expected hash {recomputed}, stored hash {entry.hash}"
                )

            expected_prev_hash = entry.hash

        return len(errors) == 0, errors
