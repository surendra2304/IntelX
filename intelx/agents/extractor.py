"""INTELX Extractor Agent: Verifiable Structured Claim Extraction and Offset Hardening."""

import difflib
import logging
import re
import unicodedata
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


def normalize_for_alignment(s: str) -> str:
    """Normalize unicode punctuation, quotes, dashes, ellipsis, and whitespace for fuzzy alignment."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = s.replace("—", "-").replace("–", "-").replace("…", "...")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def align_quote_to_document(
    quote: str,
    document_text: str,
    min_similarity: float = 0.90,
) -> tuple[str, int, int, float] | None:
    """
    Fuzzy align an LLM extracted quote to the document text.
    If similarity >= min_similarity (default 0.90), returns (snapped_verbatim_quote, start, end, ratio).
    Otherwise returns None.
    """
    if not quote or not document_text:
        return None

    # 1. Exact match fast-path
    idx = document_text.find(quote)
    if idx != -1:
        return quote, idx, idx + len(quote), 1.0

    # 2. Normalized search
    norm_q = normalize_for_alignment(quote).lower()
    if not norm_q:
        return None

    words = [w for w in re.findall(r"\b\w+\b", norm_q) if len(w) > 3]
    anchor = words[0] if words else norm_q[:10]

    doc_low = document_text.lower()
    anchor_indices = [m.start() for m in re.finditer(re.escape(anchor), doc_low)]
    if not anchor_indices:
        step = max(1, len(quote) // 4)
        anchor_indices = list(range(0, max(1, len(document_text) - len(quote)), step))

    best_match = None
    best_ratio = 0.0
    target_len = len(quote)

    for start_idx in anchor_indices:
        for delta_len in range(-30, 31, 3):
            end_idx = min(len(document_text), max(0, start_idx + target_len + delta_len))
            if end_idx <= start_idx:
                continue
            cand_slice = document_text[start_idx:end_idx]
            cand_norm = normalize_for_alignment(cand_slice).lower()
            ratio = difflib.SequenceMatcher(None, norm_q, cand_norm).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = (cand_slice, start_idx, end_idx, ratio)

    if best_match and best_ratio >= min_similarity:
        return best_match

    return None


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
    """Agent executing structured extraction with strict span alignment and attribution validation."""

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
        """Extract claims from chunks and enforce strict offset alignment and attribution invariants."""
        all_saved_claims = []
        all_entities = []
        all_events = []

        total_attempted = 0
        total_accepted = 0

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

            # HARD RULES VALIDATION AND ALIGNMENT
            for claim_data in extraction.claims:
                total_attempted += 1

                # Rule a: Fuzzy align quote to chunk text with 0.90 similarity threshold
                alignment = align_quote_to_document(
                    claim_data.quote, chunk.text, min_similarity=0.90
                )
                if alignment is None:
                    # Quote cannot be aligned with >= 0.90 similarity -> Drop claim and log event
                    logger.warning(
                        f"Dropping unverifiable claim: quote '{claim_data.quote[:40]}...' cannot be aligned to chunk {chunk.id}"
                    )
                    await RunRepo.add_event(
                        session=session,
                        run_id=run_id,
                        event_type="claim.rejected_unverifiable",
                        payload_json={
                            "chunk_id": chunk.id,
                            "unverifiable_quote": claim_data.quote,
                            "claim_text": claim_data.text,
                            "reason": "quote_similarity_below_threshold",
                        },
                    )
                    continue

                snapped_quote, rel_start, rel_end, sim_ratio = alignment
                total_accepted += 1

                # Snap quote and spans to exact verbatim chunk text
                abs_start = chunk.start_char + rel_start
                abs_end = chunk.start_char + rel_end

                # Verbatim slice is exact by construction
                exact_quote = document.text[abs_start:abs_end]
                claim_data.quote = exact_quote
                claim_data.relative_span = RelativeSpan(start=rel_start, end=rel_end)

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
                    quote=exact_quote,
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
                    quote=exact_quote,
                    support_type=EvidenceSupportType.SUPPORTS,
                    created_by_run_id=run_id,
                    created_by_agent="extractor",
                )

                all_saved_claims.append(claim_data)

        alignment_rate = (total_accepted / total_attempted) if total_attempted > 0 else 1.0
        await RunRepo.add_event(
            session=session,
            run_id=run_id,
            event_type="claim.alignment_stats",
            payload_json={
                "attempted": total_attempted,
                "accepted": total_accepted,
                "span_alignment_rate": round(alignment_rate, 4),
            },
        )

        return ExtractionResult(
            claims=all_saved_claims,
            entities=all_entities,
            events=all_events,
        )
