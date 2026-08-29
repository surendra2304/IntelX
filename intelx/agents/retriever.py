"""INTELX Retriever Agent: Document Fetching, Ingestion, and Error Classification."""

import asyncio
import logging
import urllib.parse
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
        run_id: str | None,
    ) -> tuple[
        RetrievedDoc | None,
        FetchFailure | None,
        Source | None,
        Document | None,
        list[Chunk],
    ]:
        """Fetch, normalize, and persist a single candidate with retry logic."""
        location = candidate.location.strip()
        parsed = urllib.parse.urlparse(location)

        # Internal reference bypass
        if location.startswith("internal://"):
            return None, None, None, None, []

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
                    if not fetch_res.robots_ok:
                        failure = FetchFailure(
                            location=location,
                            error_class=TaskErrorClass.LOGICAL,
                            reason=fetch_res.error or "Disallowed by robots.txt",
                        )
                        return None, failure, None, None, []

                    raw_bytes = fetch_res.content
                    content_type = fetch_res.content_type
                    kind = SourceKind.WEB
                    domain = parsed.hostname

                source, doc, chunks, _ = await ingest_and_normalize(
                    session=session,
                    raw_bytes=raw_bytes,
                    location=location,
                    kind=kind,
                    content_type=content_type,
                    title=candidate.title,
                    domain=domain,
                    created_by_run_id=run_id,
                    settings=self.settings,
                )

                retrieved_item = RetrievedDoc(
                    source_id=source.id,
                    document_id=doc.id,
                    location=location,
                    chunks_count=len(chunks),
                    source_title=source.title,
                )
                return retrieved_item, None, source, doc, chunks

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
                    try:
                        snip_text = candidate.snippet.strip()[:1000]
                        source, doc, chunks, _ = await ingest_and_normalize(
                            session=session,
                            raw_bytes=snip_text.encode("utf-8"),
                            location=location,
                            kind=SourceKind.WEB,
                            content_type="text/plain; format=snippet",
                            title=f"{candidate.title} (Snippet)"
                            if candidate.title
                            else "Web Search Snippet",
                            domain=parsed.hostname,
                            license_note="search-engine-snippet",
                            created_by_run_id=run_id,
                            settings=self.settings,
                        )
                        retrieved_item = RetrievedDoc(
                            source_id=source.id,
                            document_id=doc.id,
                            location=location,
                            chunks_count=len(chunks),
                            source_title=source.title,
                        )
                        logger.info(f"Retrieved snippet fallback for {location}")
                        return retrieved_item, None, source, doc, chunks
                    except Exception as snip_err:
                        logger.warning(f"Snippet fallback failed for {location}: {snip_err}")

                failure = FetchFailure(
                    location=location,
                    error_class=TaskErrorClass.LOGICAL,
                    reason=str(e),
                )
                return None, failure, None, None, []

            except Exception as e:
                last_error = e
                if attempt < max_attempts:
                    await asyncio.sleep(0.5)

        # After transient retry exhaustion, check snippet fallback
        if candidate.snippet and len(candidate.snippet.strip()) >= 15:
            try:
                snip_text = candidate.snippet.strip()[:1000]
                source, doc, chunks, _ = await ingest_and_normalize(
                    session=session,
                    raw_bytes=snip_text.encode("utf-8"),
                    location=location,
                    kind=SourceKind.WEB,
                    content_type="text/plain; format=snippet",
                    title=f"{candidate.title} (Snippet)"
                    if candidate.title
                    else "Web Search Snippet",
                    domain=parsed.hostname,
                    license_note="search-engine-snippet",
                    created_by_run_id=run_id,
                    settings=self.settings,
                )
                retrieved_item = RetrievedDoc(
                    source_id=source.id,
                    document_id=doc.id,
                    location=location,
                    chunks_count=len(chunks),
                    source_title=source.title,
                )
                logger.info(f"Retrieved snippet fallback for {location}")
                return retrieved_item, None, source, doc, chunks
            except Exception as snip_err:
                logger.warning(f"Snippet fallback failed for {location}: {snip_err}")

        failure = FetchFailure(
            location=location,
            error_class=TaskErrorClass.TRANSIENT,
            reason=f"Transient fetch error after {max_attempts} attempts: {last_error}",
        )
        return None, failure, None, None, []

    async def execute(
        self,
        candidates: list[SourceCandidate],
        session: AsyncSession,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> RetrieverOutput:
        output = RetrieverOutput()
        for candidate in candidates:
            ret, fail, _, _, _ = await self._fetch_single(candidate, session, run_id)
            if ret:
                output.retrieved.append(ret)
            elif fail:
                output.failures.append(fail)

        return output
