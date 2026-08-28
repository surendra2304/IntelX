"""INTELX Extractor Agent: Verifiable Structured Claim Extraction and Offset Hardening."""

import logging
import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.base import BaseAgent, format_external_document
from intelx.core.enums import (
    ClaimOrigin,
    ClaimStatus,
    ClaimType,
    EntityType,
    EvidenceSupportType,
)
from intelx.db.models import Chunk, Document
from intelx.db.repos import ClaimRepo, EvidenceRepo, RunRepo
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)

ATTRIBUTION_REGEX = re.compile(
    r"(?i)\b(?:according to|reported by|stated by|forecast by|projected by|estimated by|per)\b"
)


class RelativeSpan(BaseModel):
    """Character offsets relative to the parent chunk slice."""

    start: int
    end: int


class ExtractedClaim(BaseModel):
    """Structured claim model extracted by LLM from an external document chunk."""

    text: str
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    claim_type: ClaimType = ClaimType.FACT
    entities: list[str] = Field(default_factory=list)
    quote: str
    relative_span: RelativeSpan
    preliminary_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    rationale: str = ""


class ExtractedEntity(BaseModel):
    """Named entity identified within document chunks."""

    name: str
    type: EntityType = EntityType.OTHER
    aliases: list[str] = Field(default_factory=list)


class ExtractedEvent(BaseModel):
    """Temporal or operational event mentioned in the source."""

    description: str
    date_iso: str | None = None
    participants: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Complete extraction payload emitted by LLM for a chunk."""

    claims: list[ExtractedClaim] = Field(default_factory=list)
    entities: list[ExtractedEntity] = Field(default_factory=list)
    events: list[ExtractedEvent] = Field(default_factory=list)


class ExtractorAgent(BaseAgent):
    """Agent executing structured extraction with strict span and attribution validation."""

    SYSTEM_PROMPT = (
        "You are the INTELX Evidence Extraction Specialist.\n"
        "Your role is to extract factual claims, entities, and events strictly supported by "
        "the provided document text.\n\n"
        "MANDATORY EXTRACTION RULES:\n"
        "1. Every extracted claim MUST include an exact, verbatim 'quote' from the chunk.\n"
        "2. Provide the 'relative_span' (start and end character indices within the chunk text).\n"
        "3. For STATEMENT_OF_OPINION and FORECAST claims, the claim 'text' MUST explicitly "
        "include source attribution (e.g. 'According to <Source>, ...').\n"
        "4. NEVER invent or extrapolate claims not grounded in the chunk text."
    )

    def __init__(self, gateway: ModelGateway | None = None) -> None:
        super().__init__(role="extractor", name="ExtractorAgent", gateway=gateway)

    async def execute(
        self,
        document: Document,
        chunks: list[Chunk],
        run_id: str,
        source_id: str,
        session: AsyncSession,
        publisher: str | None = None,
        **kwargs: Any,
    ) -> ExtractionResult:
        """Extract claims from chunks and enforce strict offset and attribution invariants."""
        all_saved_claims = []
        all_entities = []
        all_events = []

        for chunk in chunks:
            # Place untrusted external text ONLY in user message with delimiters
            doc_block = format_external_document(document.id, source_id, chunk.text)
            user_prompt = (
                "Extract structured claims, entities, and events from the document chunk:\n\n"
                f"{doc_block}\n\n"
                "Ensure every claim quote is an exact verbatim substring with valid spans."
            )

            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            result = await self.gateway.complete(
                messages=messages,
                role=self.role,
                schema_model=ExtractionResult,
                run_id=run_id,
            )

            extraction: ExtractionResult = result.parsed
            all_entities.extend(extraction.entities)
            all_events.extend(extraction.events)

            # HARD RULES VALIDATION AND HARDENING
            for claim_data in extraction.claims:
                quote = claim_data.quote
                rel_start = claim_data.relative_span.start
                rel_end = claim_data.relative_span.end

                # Rule a: Verify verbatim substring in chunk. If mismatch, search exact match
                if chunk.text[rel_start:rel_end] != quote:
                    idx = chunk.text.find(quote)
                    if idx != -1:
                        rel_start = idx
                        rel_end = idx + len(quote)
                    else:
                        # Quote cannot be found verbatim in chunk -> Drop claim and log event
                        logger.warning(
                            f"Dropping unverifiable claim: quote '{quote}' not in chunk {chunk.id}"
                        )
                        await RunRepo.add_event(
                            session=session,
                            run_id=run_id,
                            event_type="claim.rejected_unverifiable",
                            payload_json={
                                "chunk_id": chunk.id,
                                "unverifiable_quote": quote,
                                "claim_text": claim_data.text,
                            },
                        )
                        continue

                # Rule b: Calculate absolute offsets into document.text and verify slice
                abs_start = chunk.start_char + rel_start
                abs_end = chunk.start_char + rel_end

                if document.text[abs_start:abs_end] != quote:
                    logger.warning(
                        f"Absolute span verification failed for quote '{quote}'. Dropping claim."
                    )
                    await RunRepo.add_event(
                        session=session,
                        run_id=run_id,
                        event_type="claim.rejected_unverifiable",
                        payload_json={"chunk_id": chunk.id, "reason": "absolute_offset_mismatch"},
                    )
                    continue

                # Rule d: STATEMENT_OF_OPINION and FORECAST must have explicit attribution
                if claim_data.claim_type in (ClaimType.STATEMENT_OF_OPINION, ClaimType.FORECAST):
                    if not ATTRIBUTION_REGEX.search(claim_data.text):
                        logger.info(
                            f"Dropping {claim_data.claim_type} missing attribution: "
                            f"{claim_data.text[:30]}"
                        )
                        await RunRepo.add_event(
                            session=session,
                            run_id=run_id,
                            event_type="claim.rejected_missing_attribution",
                            payload_json={
                                "claim_text": claim_data.text,
                                "type": claim_data.claim_type,
                            },
                        )
                        continue

                # Rule c: Persist claim into database with full lineage
                persisted_claim = await ClaimRepo.create_claim(
                    session=session,
                    run_id=run_id,
                    source_id=source_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    text_content=claim_data.text,
                    quote=quote,
                    span_start=abs_start,
                    span_end=abs_end,
                    claim_type=claim_data.claim_type,
                    subject=claim_data.subject,
                    predicate=claim_data.predicate,
                    object_val=claim_data.object,
                    entities_json=claim_data.entities,
                    confidence=claim_data.preliminary_confidence,
                    confidence_method="preliminary",
                    origin=ClaimOrigin.EXTRACTED,
                    status=ClaimStatus.ACTIVE,
                    created_by_agent="extractor",
                )

                # Rule e: Initial quote is stored as the first supporting Evidence row
                await EvidenceRepo.create_evidence(
                    session=session,
                    claim_id=persisted_claim.id,
                    source_id=source_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    span_start=abs_start,
                    span_end=abs_end,
                    quote=quote,
                    support_type=EvidenceSupportType.SUPPORTS,
                    created_by_run_id=run_id,
                    created_by_agent="extractor",
                )

                all_saved_claims.append(claim_data)

        return ExtractionResult(
            claims=all_saved_claims,
            entities=all_entities,
            events=all_events,
        )
