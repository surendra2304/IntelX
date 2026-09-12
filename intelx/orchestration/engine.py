"""INTELX Orchestration Engine: Task DAG Execution, State Machine, Gates, and Resiliency."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.agents.analyst import AnalystAgent
from intelx.agents.critic import CriticAgent
from intelx.agents.extractor import ExtractorAgent
from intelx.agents.planner import PlannerAgent
from intelx.agents.retriever import RetrieverAgent
from intelx.agents.scout import ScoutAgent, SourceCandidate
from intelx.agents.synthesizer import SynthesizerAgent
from intelx.agents.verifier import VerifierAgent
from intelx.core.enums import (
    ClaimStatus,
    RunOutcome,
    RunStatus,
    TaskErrorClass,
    TaskStatus,
    TaskType,
)
from intelx.core.errors import (
    BudgetExceededError,
    NotFoundError,
    ValidationError,
)
from intelx.core.settings import Settings, get_settings
from intelx.db.models import Chunk, Claim, Document, ResearchRun, Source, Task
from intelx.db.repos import RunRepo, SourceRepo
from intelx.orchestration.events import (
    emit_budget_warning,
    emit_event,
    emit_research_completed,
    emit_review_required,
    emit_stage_changed,
)

logger = logging.getLogger(__name__)

VALID_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.PLANNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.PLANNING: {RunStatus.DISCOVERING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.DISCOVERING: {RunStatus.RETRIEVING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.RETRIEVING: {RunStatus.EXTRACTING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.EXTRACTING: {RunStatus.VERIFYING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.VERIFYING: {RunStatus.ANALYZING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.ANALYZING: {
        RunStatus.SYNTHESIZING,
        RunStatus.DISCOVERING,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.SYNTHESIZING: {
        RunStatus.COMPLETED,
        RunStatus.REVIEW_REQUIRED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.REVIEW_REQUIRED: {
        RunStatus.SYNTHESIZING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
}


class OrchestrationEngine:
    """Core DAG engine executing resilient, evidence-driven research workflows."""

    def __init__(
        self,
        settings: Settings | None = None,
        planner_agent: PlannerAgent | None = None,
        scout_agent: ScoutAgent | None = None,
        retriever_agent: RetrieverAgent | None = None,
        extractor_agent: ExtractorAgent | None = None,
        verifier_agent: VerifierAgent | None = None,
        analyst_agent: AnalystAgent | None = None,
        critic_agent: CriticAgent | None = None,
        synthesizer_agent: SynthesizerAgent | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        from intelx.models.gateway import get_model_gateway

        self.gateway = get_model_gateway()
        self.planner = planner_agent or PlannerAgent(gateway=self.gateway)
        self.scout = scout_agent or ScoutAgent(gateway=self.gateway)
        self.retriever = retriever_agent or RetrieverAgent(
            gateway=self.gateway, settings=self.settings
        )
        self.extractor = extractor_agent or ExtractorAgent(gateway=self.gateway)
        self.verifier = verifier_agent or VerifierAgent(gateway=self.gateway)
        self.analyst = analyst_agent or AnalystAgent(gateway=self.gateway)
        self.critic = critic_agent or CriticAgent(gateway=self.gateway)
        self.synthesizer = synthesizer_agent or SynthesizerAgent(gateway=self.gateway)

    async def transition_state(
        self, session: AsyncSession, run: ResearchRun, new_status: RunStatus
    ) -> ResearchRun:
        """Enforce strict state machine transitions with live event emission."""
        current_status = run.status
        if current_status == new_status:
            return run

        allowed = VALID_TRANSITIONS.get(current_status, {RunStatus.FAILED, RunStatus.CANCELLED})

        if new_status not in allowed and new_status not in (RunStatus.FAILED, RunStatus.CANCELLED):
            raise ValidationError(
                f"Invalid state transition: '{current_status}' -> '{new_status}' is not permitted"
            )

        updated_run = await RunRepo.set_status(session, run.id, new_status)
        await emit_stage_changed(session, run.id, current_status, new_status)
        return updated_run

    async def _check_gates(self, session: AsyncSession, run_id: str) -> ResearchRun:
        """Check budget ceilings, cancellation signals, and time constraints between stages."""
        run = await RunRepo.get_run(session, run_id)
        if not run:
            raise NotFoundError(f"Run {run_id} not found")

        # 1. Cancellation Check
        if run.status == RunStatus.CANCELLED or (
            run.error_json and run.error_json.get("cancel_requested")
        ):
            if run.status != RunStatus.CANCELLED:
                run = await RunRepo.set_status(session, run_id, RunStatus.CANCELLED)
                await emit_stage_changed(session, run_id, run.status, RunStatus.CANCELLED)
            raise asyncio.CancelledError(f"Run {run_id} was cancelled by user request")

        # 0. Sync usage from Gateway
        usage = self.gateway.get_usage(run_id)
        if usage.input_tokens > 0 or usage.output_tokens > 0 or usage.usd_cost > 0:
            run.input_tokens = max(run.input_tokens, usage.input_tokens)
            run.output_tokens = max(run.output_tokens, usage.output_tokens)
            run.usd_cost = max(run.usd_cost, usage.usd_cost)
            await session.flush()

        # 2. Budget Ceiling Check
        max_usd = self.settings.MAX_RUN_USD
        if run.usd_cost >= max_usd:
            logger.warning(f"Run {run_id} exceeded budget (${run.usd_cost:.4f} >= ${max_usd:.4f})")
            await RunRepo.set_status(
                session,
                run_id,
                RunStatus.FAILED,
                outcome=RunOutcome.FAILED,
                error_json={
                    "reason": "budget_exceeded",
                    "spent_usd": run.usd_cost,
                    "max_usd": max_usd,
                },
            )
            await emit_event(
                session,
                run_id,
                "budget.exceeded",
                {"spent_usd": run.usd_cost, "max_usd": max_usd},
            )
            raise BudgetExceededError(f"Run {run_id} exceeded budget ceiling (${run.usd_cost:.2f})")

        # 3. Budget 80% Warning
        if run.usd_cost >= (0.80 * max_usd) and max_usd > 0:
            pct = (run.usd_cost / max_usd) * 100
            await emit_budget_warning(session, run_id, pct, run.usd_cost, max_usd)

        # 4. Max Execution Time Limit
        if run.started_at:
            started = run.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            elapsed_minutes = (datetime.now(UTC) - started).total_seconds() / 60.0
            if elapsed_minutes > self.settings.MAX_RUN_MINUTES:
                await RunRepo.set_status(
                    session,
                    run_id,
                    RunStatus.FAILED,
                    outcome=RunOutcome.FAILED,
                    error_json={"reason": "timeout_exceeded", "elapsed_minutes": elapsed_minutes},
                )
                raise TimeoutError(f"Run {run_id} exceeded max time limit ({elapsed_minutes:.1f}m)")

        return run

    async def execute_run(self, session: AsyncSession, run_id: str) -> ResearchRun:
        """Execute the end-to-end research DAG workflow."""
        run = await RunRepo.get_run(session, run_id)
        if not run:
            raise NotFoundError(f"Run {run_id} not found")

        scope = run.scope_json or {}
        degradations: list[str] = []
        replan_count = 0

        # Step 0: Preload parent context if followup run
        if run.parent_run_id:
            await emit_event(
                session,
                run_id,
                "followup.initialized",
                {"parent_run_id": run.parent_run_id, "mode": "challenge_and_extend"},
            )

        # Step 0.5: Handle direct resumption from REVIEW_REQUIRED
        if run.status == RunStatus.REVIEW_REQUIRED:
            stmt_claims = select(Claim).where(Claim.run_id == run_id)
            claims = list((await session.execute(stmt_claims)).scalars().all())
            run = await self.transition_state(session, run, RunStatus.SYNTHESIZING)
            await self.synthesizer.execute(
                objective=run.objective,
                claims=claims,
                session=session,
                run_id=run_id,
            )
            run = await self.transition_state(session, run, RunStatus.COMPLETED)
            run.outcome = RunOutcome.ANSWERED if claims else RunOutcome.INSUFFICIENT_EVIDENCE
            run.completed_at = datetime.now(UTC)
            await session.flush()
            await emit_research_completed(session, run_id, run.outcome)

            # External Integrations (Futuris, StrateX)
            if run.outcome == RunOutcome.ANSWERED:
                try:
                    from intelx.integrations.futuris_context import FuturisContextProvider
                    from intelx.integrations.memora_context import MemoraMemoryClient
                    from intelx.integrations.stratex_context import StratexConnector
                    
                    finding_text = f"{run.objective} (Post-Review Resolution)"
                    domain = scope.get("domain", "market")
                    
                    memora_client = MemoraMemoryClient()
                    asyncio.create_task(
                        memora_client.store_research_memory(
                            run_id=run_id,
                            objective=run.objective,
                            summary=finding_text,
                            evidence_count=1,
                            claims_count=1,
                            namespace="memora://intelx/shared",
                            tags=["intelx", "research", domain, "review-resolved"],
                        )
                    )
                    asyncio.create_task(
                        FuturisContextProvider.notify_futuris_research_relevant(
                            finding_text=finding_text, run_id=run_id, domain=domain
                        )
                    )
                    asyncio.create_task(
                        StratexConnector.notify_stratex_trade_signal(
                            finding_text=finding_text, run_id=run_id, domain=domain
                        )
                    )
                except Exception as ex:
                    logger.warning(f"Failed to dispatch external ecosystem webhooks: {ex}")

            return run

        try:
            run = await self._check_gates(session, run_id)
            # 1. PLANNING STAGE
            run = await self.transition_state(session, run, RunStatus.PLANNING)
            plan = await self.planner.execute(
                objective=run.objective,
                scope=scope,
                run_id=run_id,
            )
            stmt = (
                update(ResearchRun)
                .where(ResearchRun.id == run_id)
                .values(plan_json=plan.model_dump())
            )
            await session.execute(stmt)
            await session.flush()
            run = await self._check_gates(session, run_id)

            # Subquestion discovery & retrieval loop (with potential replan)
            while True:
                # 2. DISCOVERING STAGE
                run = await self.transition_state(session, run, RunStatus.DISCOVERING)
                run = await self._check_gates(session, run_id)

                all_candidates: list[SourceCandidate] = []
                # Ensure primary objective is scouted directly as the first high-priority target
                scouting_targets = [run.objective] + [
                    sq for sq in plan.subquestions if sq.strip().lower() != run.objective.strip().lower()
                ]
                for idx, subq in enumerate(scouting_targets):
                    scout_task = Task(
                        run_id=run_id,
                        type=TaskType.SCOUT,
                        status=TaskStatus.RUNNING,
                        payload_json={"subquestion": subq, "branch": idx},
                        started_at=datetime.now(UTC),
                    )
                    session.add(scout_task)
                    await session.flush()

                    try:
                        scout_res = await self.scout.execute(
                            subquestion=subq,
                            plan=plan,
                            session=session,
                            run_id=run_id,
                        )
                        scout_task.status = TaskStatus.SUCCEEDED
                        scout_task.result_json = {"candidates_count": len(scout_res.candidates)}
                        scout_task.finished_at = datetime.now(UTC)
                        await session.flush()
                        all_candidates.extend(scout_res.candidates)
                    except Exception as e:
                        logger.error(f"Scout task failed for '{subq}': {e}")
                        scout_task.status = TaskStatus.FAILED
                        scout_task.error_class = TaskErrorClass.LOGICAL
                        scout_task.error_json = {"error": str(e)}
                        scout_task.finished_at = datetime.now(UTC)
                        degradations.append(f"Scout failed for subquestion: {subq}")
                        await session.flush()

                # 3. RETRIEVING STAGE
                run = await self.transition_state(session, run, RunStatus.RETRIEVING)
                all_ingested: list[tuple[Source, Document, list[Chunk]]] = []

                # Deduplicate candidates across subquestion discovery branches
                unique_candidates: list[SourceCandidate] = []
                seen_locations: set[str] = set()
                for cand in all_candidates:
                    if cand.location not in seen_locations:
                        seen_locations.add(cand.location)
                        unique_candidates.append(cand)

                if unique_candidates:
                    ret_task = Task(
                        run_id=run_id,
                        type=TaskType.RETRIEVE,
                        status=TaskStatus.RUNNING,
                        payload_json={"candidates_count": len(unique_candidates)},
                        started_at=datetime.now(UTC),
                    )
                    session.add(ret_task)
                    await session.flush()

                    ret_res = await self.retriever.execute(
                        candidates=unique_candidates,
                        session=session,
                        run_id=run_id,
                    )

                    for fail in ret_res.failures:
                        degradations.append(
                            f"Retrieval failure ({fail.error_class}): "
                            f"{fail.location} - {fail.reason}"
                        )

                    ret_task.status = TaskStatus.SUCCEEDED
                    ret_task.result_json = {
                        "retrieved_count": len(ret_res.retrieved),
                        "failures_count": len(ret_res.failures),
                    }
                    ret_task.finished_at = datetime.now(UTC)
                    await session.flush()

                    for item in ret_res.retrieved:
                        source = await SourceRepo.get_source(session, item.source_id)
                        doc = await SourceRepo.get_document(session, item.document_id)
                        if source and doc:
                            stmt_c = (
                                select(Chunk)
                                .where(Chunk.document_id == doc.id)
                                .order_by(Chunk.idx.asc())
                            )
                            chunks = list((await session.execute(stmt_c)).scalars().all())
                            all_ingested.append((source, doc, chunks))

                run = await self._check_gates(session, run_id)

                # 4. EXTRACTING STAGE
                run = await self.transition_state(session, run, RunStatus.EXTRACTING)
                for source, doc, chunks in all_ingested:
                    extract_task = Task(
                        run_id=run_id,
                        type=TaskType.EXTRACT,
                        status=TaskStatus.RUNNING,
                        payload_json={"document_id": doc.id, "chunks_count": len(chunks)},
                        started_at=datetime.now(UTC),
                    )
                    session.add(extract_task)
                    await session.flush()

                    await self.extractor.execute(
                        document=doc,
                        chunks=chunks,
                        run_id=run_id,
                        source_id=source.id,
                        session=session,
                    )
                    extract_task.status = TaskStatus.SUCCEEDED
                    extract_task.finished_at = datetime.now(UTC)
                    await session.flush()

                run = await self._check_gates(session, run_id)

                stmt_claims = select(Claim).where(Claim.run_id == run_id)
                claims = list((await session.execute(stmt_claims)).scalars().all())

                # 5. VERIFYING STAGE
                run = await self.transition_state(session, run, RunStatus.VERIFYING)
                if claims:
                    await self.verifier.execute(
                        claims=claims,
                        scope=scope,
                        session=session,
                        run_id=run_id,
                        depth=scope.get("depth", "standard"),
                    )
                run = await self._check_gates(session, run_id)

                # 6. ANALYZING STAGE
                run = await self.transition_state(session, run, RunStatus.ANALYZING)
                analysis = await self.analyst.execute(claims=claims, run_id=run_id)
                run = await self._check_gates(session, run_id)

                # 7. CRITIQUE STAGE
                critique = await self.critic.execute(
                    draft_findings=[{"analysis_themes": [t.label for t in analysis.themes]}],
                    claims=claims,
                    run_id=run_id,
                )
                await emit_event(session, run_id, "critic.evaluated", critique.model_dump())

                if critique.severity == "HIGH" and replan_count < 1:
                    replan_count += 1
                    await emit_event(
                        session,
                        run_id,
                        "orchestrator.replan_triggered",
                        {"replan_iteration": replan_count},
                    )
                    continue

                break

            # 8. SYNTHESIZING STAGE
            run = await self.transition_state(session, run, RunStatus.SYNTHESIZING)
            synthesis_res = await self.synthesizer.execute(
                objective=run.objective,
                claims=claims,
                analysis=analysis,
                critique=critique,
                degradations=degradations,
                session=session,
                run_id=run_id,
            )
            run = await self._check_gates(session, run_id)

            # 9. REVIEW GATE CHECK (from SYNTHESIZING -> REVIEW_REQUIRED)
            has_disputed = any(c.status == ClaimStatus.DISPUTED for c in claims)
            requires_review = has_disputed and scope.get("depth") == "deep"

            review_decision = scope.get("review_decision")
            if requires_review and not review_decision:
                run = await self.transition_state(session, run, RunStatus.REVIEW_REQUIRED)
                disputed_ids = [c.id for c in claims if c.status == ClaimStatus.DISPUTED]
                await emit_review_required(
                    session,
                    run_id,
                    "Disputed claims in deep mode require review",
                    disputed_ids,
                )
                return run

            active_claims = [c for c in claims if c.status == ClaimStatus.ACTIVE]
            disputed_claims = [c for c in claims if c.status == ClaimStatus.DISPUTED]
            is_friday_or_enhanced = bool(
                scope.get("friday_envelope")
                or scope.get("query_scope")
                or scope.get("source_policy")
                or scope.get("friday_request_id")
                or scope.get("enforce_prompt6")
            )
            if is_friday_or_enhanced:
                if not all_ingested and not claims:
                    outcome = RunOutcome.NO_EVIDENCE_FOUND
                elif len(disputed_claims) > 0 and len(active_claims) == 0:
                    outcome = RunOutcome.CONTRADICTION_DETECTED
                elif (
                    not claims
                    or len(claims) == 0
                    or len(active_claims) == 0
                    or synthesis_res.overall_confidence_label == "Very low"
                ):
                    outcome = RunOutcome.NO_EVIDENCE_FOUND
                else:
                    outcome = RunOutcome.ANSWERED
            else:
                if (
                    not claims
                    or len(claims) == 0
                    or len(active_claims) == 0
                    or synthesis_res.overall_confidence_label == "Very low"
                ):
                    outcome = RunOutcome.INSUFFICIENT_EVIDENCE
                else:
                    outcome = RunOutcome.ANSWERED

            if degradations:
                await emit_event(
                    session,
                    run_id,
                    "run.degradations_recorded",
                    {"degradations": degradations},
                )

            # 10. COMPLETED STAGE
            usage = self.gateway.get_usage(run_id)
            run.input_tokens = usage.input_tokens
            run.output_tokens = usage.output_tokens
            run.usd_cost = usage.usd_cost

            run = await self.transition_state(session, run, RunStatus.COMPLETED)
            run.outcome = outcome
            run.completed_at = datetime.now(UTC)
            await session.flush()

            cost_summary = {
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "usd_cost": run.usd_cost,
                "tool_calls": run.tool_calls,
                "outcome": str(outcome),
            }
            await emit_research_completed(session, run_id, outcome, cost_summary)

            # 11. External Integrations (Memora, Futuris, StrateX, FRIDAY Universe)
            if outcome == RunOutcome.ANSWERED:
                try:
                    from intelx.integrations.futuris_context import FuturisContextProvider
                    from intelx.integrations.memora_context import MemoraMemoryClient
                    from intelx.integrations.stratex_context import StratexConnector

                    domain = scope.get("domain", "general")
                    target_agent = scope.get("agent") or scope.get("target_agent") or "all"

                    # Build structured research intelligence payload shared across all ecosystem agents
                    syn = synthesis_res if "synthesis_res" in locals() and synthesis_res else None
                    direct_ans = (
                        getattr(syn, "executive_summary", "")
                        or getattr(syn, "direct_answer", "")
                        or ""
                    ) if syn else ""
                    structured_findings = []
                    for f in (getattr(syn, "findings", []) or [])[:8]:
                        structured_findings.append({
                            "statement": getattr(f, "statement", str(f)),
                            "confidence": getattr(f, "confidence", 0.80),
                            "confidence_label": getattr(f, "confidence_label", "High"),
                            "claim_ids": getattr(f, "claim_ids", []),
                        })

                    # Top claims for evidence tracing
                    top_claims = []
                    for c in sorted(claims, key=lambda x: getattr(x, "confidence", 0), reverse=True)[:10]:
                        top_claims.append({
                            "id": getattr(c, "id", ""),
                            "text": getattr(c, "text", ""),
                            "confidence": round(getattr(c, "confidence", 0.80), 4),
                            "quote": getattr(c, "quote", ""),
                        })

                    rich_intel_payload = {
                        "run_id": run_id,
                        "objective": run.objective,
                        "domain": domain,
                        "outcome": str(outcome),
                        "executive_answer": direct_ans,
                        "findings": structured_findings,
                        "top_claims": top_claims,
                        "overall_confidence": getattr(syn, "overall_confidence_label", "High") if syn else "Moderate",
                        "sources_count": len(all_ingested),
                        "claims_count": len(claims),
                        "usd_cost": round(run.usd_cost or 0, 6),
                        "completed_at": datetime.now(UTC).isoformat(),
                    }

                    # Text summary for legacy webhook fields
                    findings_snip = "\n".join(
                        f"• {f['statement']}" for f in structured_findings
                    ) if structured_findings else "No structured findings."
                    finding_text = (
                        f"RESEARCH OBJECTIVE: {run.objective}\n\n"
                        f"EXECUTIVE ANSWER:\n{direct_ans}\n\n"
                        f"KEY FINDINGS ({len(structured_findings)}):\n{findings_snip}\n\n"
                        f"EVIDENCE: {len(claims)} claims from {len(all_ingested)} sources"
                    )

                    # 1. Store full research intel into Memora Cloud shared memory (all 9 FRIDAY agents)
                    memora_client = MemoraMemoryClient()
                    asyncio.create_task(
                        memora_client.store_research_memory(
                            run_id=run_id,
                            objective=run.objective,
                            summary=finding_text,
                            evidence_count=len(all_ingested),
                            claims_count=len(claims),
                            namespace="memora://intelx/shared",
                            tags=["intelx", "research", domain, str(target_agent).lower()],
                        )
                    )

                    # 2. Dispatch to Futuris Predictive Forecasting (with full structured research context)
                    asyncio.create_task(
                        FuturisContextProvider.notify_futuris_research_relevant(
                            finding_text=finding_text,
                            run_id=run_id,
                            domain=domain,
                            confidence=rich_intel_payload.get("overall_confidence", 0.80)
                            if isinstance(rich_intel_payload.get("overall_confidence"), float)
                            else 0.80,
                            extra_context=rich_intel_payload,
                        )
                    )

                    # 3. Dispatch to StrateX — always send research intel; StrateX filters relevance internally
                    asyncio.create_task(
                        StratexConnector.notify_stratex_trade_signal(
                            finding_text=finding_text,
                            run_id=run_id,
                            domain=domain,
                            extra_context=rich_intel_payload,
                        )
                    )
                    logger.info(
                        f"[IntelX→Ecosystem] Dispatched rich research intel for '{run.objective[:50]}' "
                        f"({len(structured_findings)} findings, {len(claims)} claims) "
                        f"→ Memora, Futuris, StrateX"
                    )
                except Exception as ex:
                    logger.warning(f"Failed to dispatch external ecosystem webhooks: {ex}", exc_info=True)

            return run

        except asyncio.CancelledError:
            logger.info(f"Run {run_id} cancellation acknowledged.")
            run.status = RunStatus.CANCELLED
            run.outcome = RunOutcome.CANCELLED
            run.completed_at = datetime.now(UTC)
            await session.flush()
            await emit_stage_changed(session, run_id, run.status, RunStatus.CANCELLED)
            return run

        except BudgetExceededError as e:
            logger.error(f"Run {run_id} aborted on budget constraint: {e}")
            run.status = RunStatus.FAILED
            run.outcome = RunOutcome.FAILED
            run.completed_at = datetime.now(UTC)
            await session.flush()
            return run

        except Exception as e:
            logger.exception(f"Unhandled error during run {run_id} execution: {e}")
            run.status = RunStatus.FAILED
            run.outcome = RunOutcome.FAILED
            run.error_json = {"error": str(e), "type": type(e).__name__}
            run.completed_at = datetime.now(UTC)
            await session.flush()
            await emit_event(session, run_id, "run.failed", {"error": str(e)})
            return run
