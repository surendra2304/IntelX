"""INTELX Retriever Agent: Document Fetching, Ingestion, and Error Classification."""

import asyncio
import logging
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.base import BaseAgent
from intelx.agents.scout import SourceCandidate
from intelx.connectors.files import FileConnector
from intelx.connectors.web import HttpFetchConnector
from intelx.core.enums import SourceKind, TaskErrorClass
from intelx.core.errors import (
    ContentSizeExceededError,
    DomainPolicyError,
    RobotsDisallowedError,
    SecurityError,
    SSRFBlockedError,
    UnsupportedContentTypeError,
)
from intelx.core.settings import Settings, get_settings
from intelx.db.models import Chunk, Document, Source
from intelx.db.repos import SourceRepo
from intelx.memory.normalize import ingest_and_normalize
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class RetrievedDoc(BaseModel):
    """Metadata and chunk identifiers for a successfully ingested document."""

    source_id: str
    document_id: str
    location: str
    chunks_count: int
    source_title: str | None = None


class FetchFailure(BaseModel):
    """Structured capture of fetch and ingestion errors."""

    location: str
    error_class: TaskErrorClass
    reason: str


class RetrieverOutput(BaseModel):
    """Aggregated outcome of document retrieval pipeline."""

    retrieved: list[RetrievedDoc] = Field(default_factory=list)
    failures: list[FetchFailure] = Field(default_factory=list)


@dataclass
class IngestPlan:
    """Bytes to persist, decided by a fetch that is already over.

    Carrying this between the two passes in ``execute`` is what keeps the network
    out of the write transaction: a plan holds no session and writes nothing.
    """

    location: str
    raw_bytes: bytes
    content_type: str
    kind: SourceKind
    domain: str | None
    title: str | None
    license_note: str | None = None


@dataclass
class CachedHit:
    """A candidate already ingested, so nothing was fetched or written."""

    location: str
    source: Source
    document: Document
    chunks: list[Chunk] = field(default_factory=list)


class RetrieverAgent(BaseAgent):
    """Agent executing parallel fetching and ingestion of source candidates."""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        settings: Settings | None = None,
        http_connector: HttpFetchConnector | None = None,
        file_connector: FileConnector | None = None,
    ) -> None:
        super().__init__(role="retriever", name="RetrieverAgent", gateway=gateway)
        self.settings = settings or get_settings()
        self.http_connector = http_connector or HttpFetchConnector(settings=self.settings)
        self.file_connector = file_connector or FileConnector(settings=self.settings)
        self._semaphore = asyncio.Semaphore(self.settings.MAX_CONCURRENT_FETCHES)

    async def _fetch_single(
        self,
        candidate: SourceCandidate,
        session: AsyncSession,
    ) -> IngestPlan | CachedHit | FetchFailure | None:
        """Decide what to ingest for one candidate, without writing anything.

        Every network call and every fallback decision lives here so that ``execute``
        can finish all of them before any row is written. Ingestion moved to
        ``_persist``; nothing in this method touches the database except the
        read-only cache bypass.
        """
        location = candidate.location.strip()
        parsed = urllib.parse.urlparse(location)

        # Internal reference bypass
        if location.startswith("internal://"):
            return None

        # Instant cache bypass: check if source was already ingested into database
        from sqlalchemy import select

        stmt_s = select(Source).where(Source.location == location)
        existing_src = (await session.execute(stmt_s)).scalar_one_or_none()
        if existing_src:
            doc = await SourceRepo.get_document_by_source_id(session, existing_src.id)
            if doc:
                stmt_c = select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.idx.asc())
                chunks = list((await session.execute(stmt_c)).scalars().all())
                return CachedHit(
                    location=location,
                    source=existing_src,
                    document=doc,
                    chunks=chunks,
                )

        is_file = (
            parsed.scheme in ("file", "")
            or Path(location).exists()
            or location.startswith("/")
            or (len(location) > 2 and location[1] == ":")
        )

        max_attempts = 2  # Transient retry once
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                if is_file:
                    clean_path = location.removeprefix("file://")
                    file_res = await self.file_connector.fetch(clean_path)
                    raw_bytes = file_res.raw_bytes
                    content_type = file_res.content_type
                    kind = SourceKind.FILE
                    domain = None
                else:
                    fetch_res = await self.http_connector.fetch(location)
                    if (
                        (not fetch_res.robots_ok or not fetch_res.content)
                        and candidate.snippet
                        and len(candidate.snippet.strip()) >= 15
                    ):
                        logger.info(
                            f"Using snippet fallback for {location} (robots/empty response)"
                        )
                        raw_bytes = f"{candidate.title}\n\n{candidate.snippet.strip()}".encode()
                        content_type = "text/plain; format=snippet"
                        kind = SourceKind.WEB
                        domain = parsed.hostname
                    elif not fetch_res.robots_ok:
                        failure = FetchFailure(
                            location=location,
                            error_class=TaskErrorClass.LOGICAL,
                            reason=fetch_res.error or "Disallowed by robots.txt",
                        )
                        return failure
                    else:
                        raw_bytes = fetch_res.content
                        content_type = fetch_res.content_type
                        kind = SourceKind.WEB
                        domain = parsed.hostname

                return IngestPlan(
                    location=location,
                    raw_bytes=raw_bytes,
                    content_type=content_type,
                    kind=kind,
                    domain=domain,
                    title=candidate.title,
                )

            except (
                DomainPolicyError,
                RobotsDisallowedError,
                UnsupportedContentTypeError,
                ContentSizeExceededError,
                SSRFBlockedError,
                SecurityError,
                FileNotFoundError,
            ) as e:
                # Logical security/format failure - check snippet fallback
                logger.info(f"Logical fetch rejection for {location}: {e}")
                if candidate.snippet and len(candidate.snippet.strip()) >= 15:
                    return IngestPlan(
                        location=location,
                        raw_bytes=candidate.snippet.strip()[:1000].encode("utf-8"),
                        content_type="text/plain; format=snippet",
                        kind=SourceKind.WEB,
                        domain=parsed.hostname,
                        title=f"{candidate.title} (Snippet)"
                        if candidate.title
                        else "Web Search Snippet",
                        license_note="search-engine-snippet",
                    )

                failure = FetchFailure(
                    location=location,
                    error_class=TaskErrorClass.LOGICAL,
                    reason=str(e),
                )
                return failure

            except Exception as e:
                last_error = e
                if attempt < max_attempts:
                    await asyncio.sleep(0.5)

        # After transient retry exhaustion, check snippet fallback
        if candidate.snippet and len(candidate.snippet.strip()) >= 15:
            return IngestPlan(
                location=location,
                raw_bytes=candidate.snippet.strip()[:1000].encode("utf-8"),
                content_type="text/plain; format=snippet",
                kind=SourceKind.WEB,
                domain=parsed.hostname,
                title=f"{candidate.title} (Snippet)"
                if candidate.title
                else "Web Search Snippet",
                license_note="search-engine-snippet",
            )

        failure = FetchFailure(
            location=location,
            error_class=TaskErrorClass.TRANSIENT,
            reason=f"Transient fetch error after {max_attempts} attempts: {last_error}",
        )
        return failure

    async def _persist(
        self,
        plan: IngestPlan,
        session: AsyncSession,
        run_id: str | None,
    ) -> RetrievedDoc:
        """Normalize and store one fetched document. No network happens here."""
        source, doc, chunks, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=plan.raw_bytes,
            location=plan.location,
            kind=plan.kind,
            content_type=plan.content_type,
            title=plan.title,
            domain=plan.domain,
            license_note=plan.license_note,
            created_by_run_id=run_id,
            settings=self.settings,
        )
        return RetrievedDoc(
            source_id=source.id,
            document_id=doc.id,
            location=plan.location,
            chunks_count=len(chunks),
            source_title=source.title,
        )

    async def execute(
        self,
        candidates: list[SourceCandidate],
        session: AsyncSession,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> RetrieverOutput:
        # Every fetch first, then every write. SQLite permits one writer, so a
        # single ingested candidate would otherwise hold that lock across the HTTP
        # fetches for all the ones still to come -- measured at 32s, which is what
        # turns a concurrent research submission into a 500. Doing all the network
        # first costs no extra transactions: the rows still leave as the single
        # commit at the next stage boundary.
        plans: list[IngestPlan] = []
        cached: list[CachedHit] = []
        failures: list[FetchFailure] = []

        # no_autoflush covers the fetch phase only. It stops the cache-bypass SELECTs
        # from flushing rows the caller left pending, which would take the writer lock
        # mid-fetch. It deliberately stops at the end of this block: holding it into
        # the write pass would keep a stale read snapshot open, and a write on a
        # stale snapshot fails outright rather than waiting.
        with session.no_autoflush:
            for candidate in candidates:
                outcome = await self._fetch_single(candidate, session)
                if isinstance(outcome, IngestPlan):
                    plans.append(outcome)
                elif isinstance(outcome, CachedHit):
                    cached.append(outcome)
                elif isinstance(outcome, FetchFailure):
                    failures.append(outcome)

        output = RetrieverOutput(failures=failures)

        for hit in cached:
            output.retrieved.append(
                RetrievedDoc(
                    source_id=hit.source.id,
                    document_id=hit.document.id,
                    location=hit.location,
                    chunks_count=len(hit.chunks),
                    source_title=hit.source.title,
                )
            )

        for plan in plans:
            try:
                output.retrieved.append(await self._persist(plan, session, run_id))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Snippet fallback failed for {plan.location}: {exc}")
                output.failures.append(
                    FetchFailure(
                        location=plan.location,
                        error_class=TaskErrorClass.LOGICAL,
                        reason=str(exc),
                    )
                )

        return output
