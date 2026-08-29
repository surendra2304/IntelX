"""INTELX Verifier Agent: Cross-Source Corroboration and Contradiction Detection."""

import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.base import BaseAgent
from intelx.agents.extractor import ExtractorAgent
from intelx.agents.retriever import RetrieverAgent
from intelx.agents.scout import ScoutAgent
from intelx.core.confidence import compute_confidence_score
from intelx.core.credibility import SourceCredibilityScorer
from intelx.core.enums import (
    ClaimStatus,
    ClaimType,
    EvidenceSupportType,
    TrustTier,
)
from intelx.core.independence import is_independent_evidence
from intelx.db.models import Chunk, Claim, Document
from intelx.db.repos import EvidenceRepo, RunRepo, SourceRepo
from intelx.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class VerificationVerdict(BaseModel):
    """Structured verdict from LLM comparing candidate evidence against an active claim."""

    verdict: str = Field(
        description="SUPPORTED, PARTIALLY_SUPPORTED, CONTRADICTED, or UNVERIFIABLE"
    )
    support_type: EvidenceSupportType = EvidenceSupportType.SUPPORTS
    confidence_adjustment: float = Field(default=0.0, ge=-0.10, le=0.10)
    reasoning: str
    contradiction_details: str | None = None


class VerifierAgent(BaseAgent):
    """Agent executing deep multi-source cross-examination and contradiction detection."""

    SYSTEM_PROMPT = (
        "You are the INTELX Verification Authority.\n"
        "Your role is to rigorously cross-examine claims against candidate evidence.\n"
        "Classify the evidentiary relationship into: SUPPORTED, PARTIALLY_SUPPORTED, "
        "CONTRADICTED, or UNVERIFIABLE.\n"
        "If contradicting, explain the exact empirical disagreement.\n"
        "Provide a bounded confidence adjustment between -0.10 and +0.10 with written rationale."
    )

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        scout_agent: ScoutAgent | None = None,
        retriever_agent: RetrieverAgent | None = None,
        extractor_agent: ExtractorAgent | None = None,
    ) -> None:
        super().__init__(role="verifier", name="VerifierAgent", gateway=gateway)
        self.scout = scout_agent or ScoutAgent(gateway=self.gateway)
        self.retriever = retriever_agent or RetrieverAgent(gateway=self.gateway)
        self.extractor = extractor_agent or ExtractorAgent(gateway=self.gateway)

    async def execute(
        self,
        claims: list[Claim],
        scope: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
        run_id: str | None = None,
        depth: str = "standard",
        **kwargs: Any,
    ) -> list[Claim]:
        """Verify priority claims, record independent corroborations or contradictions."""
        if not session or not run_id:
            return claims

        # Filter important claims based on depth
        if depth.lower() == "deep":
            target_claims = claims
        else:
            target_claims = [
                c
                for c in claims
                if c.claim_type in (ClaimType.FACT, ClaimType.MEASUREMENT, ClaimType.EVENT)
            ]

        for claim in target_claims:
            # 1. Fetch original source and document
            orig_source = await SourceRepo.get_source(session, claim.source_id)
            orig_doc = await SourceRepo.get_document(session, claim.document_id)

            if not orig_source or not orig_doc:
                continue

            # 2. Scout for alternative corroborating/refuting evidence
            query_phrasing = f"evidence {claim.predicate or ''} {claim.subject or claim.text[:60]}"
            scout_res = await self.scout.execute(
                subquestion=query_phrasing,
                already_seen=[orig_source.location],
                session=session,
                run_id=run_id,
            )

            if not scout_res.candidates:
                continue

            # 3. Retrieve new candidate documents
            ret_res = await self.retriever.execute(
                candidates=scout_res.candidates[:2],
                session=session,
                run_id=run_id,
            )

            independent_supports = 0
            has_standard_or_trusted_support = orig_source.trust_tier in (
                TrustTier.STANDARD,
                TrustTier.TRUSTED,
            )
            strongest_tier = orig_source.trust_tier
            is_contradicted = False

            for doc_meta in ret_res.retrieved:
                new_source = await SourceRepo.get_source(session, doc_meta.source_id)
                new_doc = await SourceRepo.get_document(session, doc_meta.document_id)
                if not new_source or not new_doc:
                    continue

                # Query chunks for new document
                stmt = select(Document).where(Document.id == doc_meta.document_id)
                doc_obj = (await session.execute(stmt)).scalar_one_or_none()
                stmt_chunks = (
                    select(Chunk)
                    .where(Chunk.document_id == doc_meta.document_id)
                    .order_by(Chunk.idx.asc())
                )
                chunks_list = list((await session.execute(stmt_chunks)).scalars().all())
                if not doc_obj or not chunks_list:
                    continue

                # 4. Extract claims from new document
                extraction = await self.extractor.execute(
                    document=doc_obj,
                    chunks=chunks_list,
                    run_id=run_id,
                    source_id=new_source.id,
                    session=session,
                )

                for new_claim_data in extraction.claims:
                    # 5. Independence Check
                    is_indep, indep_reason = is_independent_evidence(
                        orig_source,
                        orig_doc,
                        claim.quote,
                        new_source,
                        new_doc,
                        new_claim_data.quote,
                    )

                    # 6. Evaluate relationship via gateway
                    eval_prompt = (
                        f"ORIGINAL CLAIM: {claim.text}\n"
                        f"ORIGINAL QUOTE: {claim.quote}\n\n"
                        f"CANDIDATE CLAIM: {new_claim_data.text}\n"
                        f"CANDIDATE QUOTE: {new_claim_data.quote}\n\n"
                        "Evaluate if the candidate claim supports, partially supports, "
                        "contradicts, or is unrelated/unverifiable relative to the original claim."
                    )

                    messages = [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": eval_prompt},
                    ]

                    verdict_res = await self.gateway.complete(
                        messages=messages,
                        role="verifier",
                        schema_model=VerificationVerdict,
                        run_id=run_id,
                    )
                    verdict: VerificationVerdict = verdict_res.parsed

                    # Compute exact absolute span in new document
                    ev_quote = new_claim_data.quote
                    ev_start = new_doc.text.find(ev_quote)
                    if ev_start == -1:
                        ev_start = chunks_list[0].start_char + new_claim_data.relative_span.start
                        ev_end = chunks_list[0].start_char + new_claim_data.relative_span.end
                    else:
                        ev_end = ev_start + len(ev_quote)

                    # 7. Contradiction Handling
                    if (
                        verdict.verdict.upper() == "CONTRADICTED"
                        or verdict.support_type == EvidenceSupportType.CONTRADICTS
                    ):
                        is_contradicted = True
                        claim.status = ClaimStatus.DISPUTED

                        # Look up persisted new claims to mark disputed as well
                        stmt_new = select(Claim).where(
                            Claim.run_id == run_id,
                            Claim.source_id == new_source.id,
                            Claim.quote == new_claim_data.quote,
                        )
                        new_claim_rows = list((await session.execute(stmt_new)).scalars().all())
                        for ncr in new_claim_rows:
                            ncr.status = ClaimStatus.DISPUTED

                        # Emit 'claim.disputed' event
                        await RunRepo.add_event(
                            session=session,
                            run_id=run_id,
                            event_type="claim.disputed",
                            payload_json={
                                "claim_id_1": claim.id,
                                "claim_id_2": new_claim_rows[0].id if new_claim_rows else None,
                                "reason": verdict.contradiction_details or verdict.reasoning,
                            },
                        )

                        # Record contradicting evidence rows on both sides
                        await EvidenceRepo.create_evidence(
                            session=session,
                            claim_id=claim.id,
                            source_id=new_source.id,
                            document_id=new_doc.id,
                            chunk_id=chunks_list[0].id,
                            span_start=ev_start,
                            span_end=ev_end,
                            quote=ev_quote,
                            support_type=EvidenceSupportType.CONTRADICTS,
                            created_by_run_id=run_id,
                            created_by_agent="verifier",
                            independent_of_json=[orig_source.id] if is_indep else [],
                        )
                        continue

                    # 8. Supporting Evidence
                    elif verdict.verdict.upper() in ("SUPPORTED", "PARTIALLY_SUPPORTED"):
                        if is_indep:
                            independent_supports += 1
                            if new_source.trust_tier in (TrustTier.STANDARD, TrustTier.TRUSTED):
                                has_standard_or_trusted_support = True
                                strongest_tier = new_source.trust_tier

                        # Create supporting evidence link
                        await EvidenceRepo.create_evidence(
                            session=session,
                            claim_id=claim.id,
                            source_id=new_source.id,
                            document_id=new_doc.id,
                            chunk_id=chunks_list[0].id,
                            span_start=ev_start,
                            span_end=ev_end,
                            quote=ev_quote,
                            support_type=verdict.support_type,
                            created_by_run_id=run_id,
                            created_by_agent="verifier",
                            independent_of_json=[orig_source.id] if is_indep else [],
                        )

            # 9. Enforce QUARANTINE Rule: cannot exceed 0.50 without standard/trusted support
            if (
                orig_source.trust_tier == TrustTier.QUARANTINE
                and not has_standard_or_trusted_support
            ):
                strongest_tier = TrustTier.QUARANTINE

            # 10. Recompute and persist final confidence score
            if not is_contradicted:
                cred_score = None
                if orig_source and orig_source.location:
                    domain_hint = scope.get("domain_hint") if scope else None
                    cred_score, _ = SourceCredibilityScorer.score_source(
                        orig_source.location, domain_hint
                    )

                ai_conf = None
                if (
                    hasattr(self.gateway, "_ai_universe_provider")
                    and self.gateway._ai_universe_provider
                ):
                    ai_conf = self.gateway._ai_universe_provider.last_metadata.get("confidence")

                score, label, _ = compute_confidence_score(
                    strongest_tier=strongest_tier,
                    independent_corroborations=independent_supports,
                    claim_type=claim.claim_type,
                    llm_adjustment=0.0,
                    rationale="Post-verification composite evaluation",
                    credibility_score=cred_score,
                    ai_universe_confidence=ai_conf,
                )
                claim.confidence = score
                claim.confidence_method = "v1-composite"

        await session.flush()
        return claims
