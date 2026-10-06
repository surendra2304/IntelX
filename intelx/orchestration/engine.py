"""INTELX Orchestration Engine: Task DAG Execution, State Machine, Gates, and Resiliency."""

import asyncio
import logging
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import PendingRollbackError
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
    ProviderError,
    ValidationError,
)
from intelx.core.settings import Settings, get_settings
from intelx.db.models import Chunk, Claim, Document, ResearchRun, Source, Task
from intelx.db.repos import RunRepo, SourceRepo
from intelx.db.session import release_writer_lock
from intelx.orchestration.events import (
    emit_budget_warning,
    emit_event,
    emit_research_completed,
    emit_review_required,
    emit_stage_changed,
)

logger = logging.getLogger(__name__)


async def _dispatch_external_research(
    *,
    run_id: str,
    objective: str,
    finding_text: str,
    domain: str,
    evidence_count: int,
    claims_count: int,
    tags: list[str],
    extra_context: dict | None = None,
    confidence: float = 0.80,
) -> dict:
    """Await and report each cross-agent delivery instead of detaching tasks."""
    from intelx.integrations.ecosystem_dispatch import dispatch_sequentially
    from intelx.integrations.futuris_context import FuturisContextProvider
    from intelx.integrations.memora_context import MemoraMemoryClient
    from intelx.integrations.stratex_context import StratexConnector

    memory = MemoraMemoryClient()
    return await dispatch_sequentially(
        [
            (
                "Memora",
                lambda: memory.store_research_memory(
                    run_id=run_id,
                    objective=objective,
                    summary=finding_text,
                    evidence_count=evidence_count,
                    claims_count=claims_count,
                    namespace="memora://intelx/shared",
                    tags=tags,
                ),
            ),
            (
                "Futuris",
                lambda: FuturisContextProvider.notify_futuris_research_relevant(
                    finding_text=finding_text,
                    run_id=run_id,
                    domain=domain,
                    confidence=confidence,
                    extra_context=extra_context,
                ),
            ),
            (
                "StrateX",
                lambda: StratexConnector.notify_stratex_trade_signal(
                    finding_text=finding_text,
                    run_id=run_id,
                    domain=domain,
                    extra_context=extra_context,
                ),
            ),
        ],
        logger=logger,
    )


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
        """Enforce strict state machine transitions with live event emission.

        The commit at the end is load-bearing. set_status flushes but does not
        end the transaction, so without it SQLite's single writer lock stayed
        held from this transition until the next release_writer_lock -- which is
        placed before the *next* stage's slow calls, so the lock spanned a whole
        stage. Measured on the five-concurrent-run scenario: intra-transaction
        gaps up to 5.92s, longest writer-lock hold 6.26s, all five workers
        blocked together for ~5.5s until busy_timeout, with SQLITE_BUSY
        (code 5) failing the run. Committing here ends the transaction the
        moment its writes are done, so no transaction spans a stage. It adds no
        writes: the same status UPDATE and event INSERT were already issued,
        they are just committed at the point they are made.
        """
        current_status = run.status
        if current_status == new_status:
            return run

        allowed = VALID_TRANSITIONS.get(current_status, {RunStatus.FAILED, RunStatus.CANCELLED})

        if new_status not in allowed and new_status not in (RunStatus.FAILED, RunStatus.CANCELLED):
            raise ValidationError(
                f"Invalid state transition: '{current_status}' -> '{new_status}' is not permitted"
            )

        # The commit and the two writes below are one write phase, so they share the
        # block. The commit is inside it because it flushes whatever the stage
        # left pending -- the scout task rows, for instance -- and that flush is
        # itself a batched INSERT that must not be the first write of a deferred
        # transaction. See db.engine.write_transaction: writing on a stale read
        # snapshot is refused outright under concurrency and "database is locked"
        # then poisons the session. Same writes as before, only the transaction
        # opener changes.
        updated_run = await RunRepo.set_status(session, run.id, new_status)
        await emit_stage_changed(session, run.id, current_status, new_status)
        await session.commit()
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

        # 2. Apply both caller-requested and operator-defined budget ceilings.
        run_budget = (run.scope_json or {}).get("budget") or {}
        try:
            requested_usd = float(run_budget.get("max_usd", self.settings.MAX_RUN_USD))
            requested_minutes = int(run_budget.get("max_minutes", self.settings.MAX_RUN_MINUTES))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Run {run_id} has an invalid budget configuration") from exc
        if not math.isfinite(requested_usd) or requested_usd < 0 or requested_minutes < 1:
            raise ValidationError(f"Run {run_id} has an invalid budget configuration")
        max_usd = min(requested_usd, self.settings.MAX_RUN_USD)
        max_minutes = min(requested_minutes, self.settings.MAX_RUN_MINUTES)
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
            if elapsed_minutes > max_minutes:
                await RunRepo.set_status(
                    session,
                    run_id,
                    RunStatus.FAILED,
                    outcome=RunOutcome.FAILED,
                    error_json={"reason": "timeout_exceeded", "elapsed_minutes": elapsed_minutes},
                )
                raise TimeoutError(f"Run {run_id} exceeded max time limit ({elapsed_minutes:.1f}m)")

        return run

    async def _settle_terminal_state(
        self,
        session: AsyncSession,
        run_id: str,
        status: RunStatus,
        outcome: RunOutcome,
        error_json: dict[str, Any] | None = None,
    ) -> ResearchRun | None:
        """Persist a terminal state for a run whose own transaction has failed.

        A database error inside the DAG -- the measured
        `(sqlite3.OperationalError) database is locked` on `INSERT INTO claims` --
        leaves the session's transaction deactivated. Writing the terminal state on
        that session raises `PendingRollbackError` from inside the error handler
        itself, so `execute_run` propagates, the caller never reaches its commit,
        and the run is stranded in whatever stage it died in: not terminal, no
        reason recorded, and never handed out by `get_or_claim_next_queued_job`
        again.

        The rollback is conditional. A stage can also fail while its session is
        perfectly healthy -- the budget ceiling raises before anything goes wrong --
        and that transaction may already hold writes worth keeping, such as the
        `budget.exceeded` event. Rolling back unconditionally discarded those. So
        the terminal write is attempted first and the rollback only happens if the
        session refuses it.

        The commit is deliberate -- the terminal state has to survive whatever the
        caller does next, so it must not depend on the caller reaching its own
        commit.
        """

        async def _write() -> ResearchRun:
            updated = await RunRepo.set_status(
                session=session,
                run_id=run_id,
                status=status,
                outcome=outcome,
                error_json=error_json,
            )
            await session.commit()
            return updated

        label = getattr(status, "value", status)
        try:
            return await _write()
        except PendingRollbackError:
            # The failure came out of the database itself, so SQLAlchemy has
            # deactivated this session's transaction and every further write on it
            # raises. Rolling back is the only way back to a usable transaction.
            logger.warning(
                "Session transaction poisoned by run failure; rolling back to "
                "persist %s for run %s",
                label,
                run_id,
            )
        except Exception:
            logger.exception(
                "Could not persist %s for run %s; it remains non-terminal", label, run_id
            )
            return None

        try:
            await session.rollback()
            return await _write()
        except Exception:
            logger.exception(
                "Could not persist %s for run %s after rollback; it remains non-terminal",
                label,
                run_id,
            )
            return None

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
            # Release the writer lock before the slow synthesis; see
            # db.session.release_writer_lock for why this boundary exists.
            run = await release_writer_lock(session, run)
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
                    finding_text = f"{run.objective} (Post-Review Resolution)"
                    domain = scope.get("domain", "market")
                    # Delivery is external HTTP with its own budget; the writer
                    # lock must not span it.
                    run = await release_writer_lock(session, run)
                    delivery_outcomes = await _dispatch_external_research(
                        run_id=run_id,
                        objective=run.objective,
                        finding_text=finding_text,
                        domain=domain,
                        evidence_count=1,
                        claims_count=1,
                        tags=["intelx", "research", domain, "review-resolved"],
                    )
                    logger.info(
                        "IntelX review-resolved ecosystem attempts completed for %s: %s",
                        run_id,
                        {
                            name: value.get("status", "unknown")
                            for name, value in delivery_outcomes.items()
                        },
                    )
                except Exception as ex:
                    logger.warning(f"Failed to dispatch external ecosystem webhooks: {ex}")

            return run

        try:
            run = await self._check_gates(session, run_id)
            # 1. PLANNING STAGE
            run = await self.transition_state(session, run, RunStatus.PLANNING)
            run = await release_writer_lock(session, run)
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
            # Same reason transition_state commits: this is the last write of the
            # planning stage, so end the transaction here rather than letting it
            # run on into the discovering transition below.
            await session.commit()
            run = await self._check_gates(session, run_id)

            # Subquestion discovery & retrieval loop (with potential replan)
            while True:
                # 2. DISCOVERING STAGE
                run = await self.transition_state(session, run, RunStatus.DISCOVERING)
                run = await self._check_gates(session, run_id)
                run = await release_writer_lock(session, run)

                all_candidates: list[SourceCandidate] = []
                failed_scout_branches = 0
                # Ensure primary objective is scouted directly as the first high-priority target
                scouting_targets = [run.objective] + [
                    sq
                    for sq in plan.subquestions
                    if sq.strip().lower() != run.objective.strip().lower()
                ]
                # The scout task rows stay pending through the loop and are written by
                # the RETRIEVING boundary below. Flushing them here would take SQLite's
                # single writer lock on the first iteration and hold it across every
                # scout's network calls; committing per iteration instead trades that
                # for extra write transactions, which is what made five concurrent
                # workers collide. no_autoflush stops the SELECTs the scout runs from
                # forcing the pending rows out early.
                with session.no_autoflush:
                    for idx, subq in enumerate(scouting_targets):
                        scout_task = Task(
                            run_id=run_id,
                            type=TaskType.SCOUT,
                            status=TaskStatus.RUNNING,
                            payload_json={"subquestion": subq, "branch": idx},
                            started_at=datetime.now(UTC),
                        )
                        session.add(scout_task)

                        try:
                            scout_res = await self.scout.execute(
                                subquestion=subq,
                                plan=plan,
                                session=session,
                                run_id=run_id,
                            )
                            scout_task.status = TaskStatus.SUCCEEDED
                            scout_task.result_json = {
                                "candidates_count": len(scout_res.candidates),
                                "search_failures": scout_res.search_failures,
                            }
                            scout_task.finished_at = datetime.now(UTC)
                            all_candidates.extend(scout_res.candidates)
                            if scout_res.search_failures:
                                failed_scout_branches += 1
                                degradations.append(
                                    f"Scout search providers failed for subquestion: {subq}"
                                )
                        except Exception as e:
                            logger.error(f"Scout task failed for '{subq}': {e}")
                            scout_task.status = TaskStatus.FAILED
                            scout_task.error_class = (
                                TaskErrorClass.TRANSIENT
                                if isinstance(e, ProviderError)
                                else TaskErrorClass.LOGICAL
                            )
                            scout_task.error_json = {
                                "type": type(e).__name__,
                                "error": str(e),
                                "details": getattr(e, "details", {}),
                            }
                            scout_task.finished_at = datetime.now(UTC)
                            degradations.append(f"Scout failed for subquestion: {subq}")
                            if isinstance(e, ProviderError):
                                failed_scout_branches += 1

                if failed_scout_branches and not all_candidates:
                    raise ProviderError(
                        "Source discovery was incomplete and returned no candidates; refusing to report a no-evidence result.",
                        details={
                            "failed_scout_branches": failed_scout_branches,
                            "scouting_branches": len(scouting_targets),
                        },
                    )

                # 3. RETRIEVING STAGE
                run = await self.transition_state(session, run, RunStatus.RETRIEVING)
                run = await release_writer_lock(session, run)
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
                    # Left pending: flushing here takes SQLite's single writer lock
                    # before the retriever's first HTTP fetch and holds it for the
                    # whole batch. The row is written by the EXTRACTING boundary.
                    session.add(ret_task)

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
                run = await release_writer_lock(session, run)
                extract_tasks: list[Task] = []
                extract_documents: list[tuple[str, Document, list[Chunk]]] = []
                for source, doc, chunks in all_ingested:
                    extract_task = Task(
                        run_id=run_id,
                        type=TaskType.EXTRACT,
                        status=TaskStatus.RUNNING,
                        payload_json={"document_id": doc.id, "chunks_count": len(chunks)},
                        started_at=datetime.now(UTC),
                    )
                    # Left pending for the same reason as the scout and retrieve
                    # task rows; the write is the stage boundary below.
                    session.add(extract_task)
                    extract_tasks.append(extract_task)
                    extract_documents.append((source.id, doc, chunks))

                # One batched call, not one per document: the extractor runs every
                # model call for the whole batch before it writes anything, so the
                # writer lock is not held across the batch's remaining model calls.
                await self.extractor.execute_many(
                    documents=extract_documents,
                    run_id=run_id,
                    session=session,
                )
                for extract_task in extract_tasks:
                    extract_task.status = TaskStatus.SUCCEEDED
                    extract_task.finished_at = datetime.now(UTC)

                run = await self._check_gates(session, run_id)

                stmt_claims = select(Claim).where(Claim.run_id == run_id)
                claims = list((await session.execute(stmt_claims)).scalars().all())

                # 5. VERIFYING STAGE
                run = await self.transition_state(session, run, RunStatus.VERIFYING)
                run = await release_writer_lock(session, run)
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
                run = await release_writer_lock(session, run)
                analysis = await self.analyst.execute(claims=claims, run_id=run_id)
                run = await self._check_gates(session, run_id)
                run = await release_writer_lock(session, run)

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
            # Same boundary as the resumption path: the synthesizer performs
            # external web fetches, so the writer lock must not span it.
            run = await release_writer_lock(session, run)
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
                    domain = scope.get("domain", "general")
                    target_agent = scope.get("agent") or scope.get("target_agent") or "all"

                    # Build structured research intelligence payload shared across all ecosystem agents
                    syn = synthesis_res if "synthesis_res" in locals() and synthesis_res else None
                    direct_ans = (
                        (
                            getattr(syn, "executive_summary", "")
                            or getattr(syn, "direct_answer", "")
                            or ""
                        )
                        if syn
                        else ""
                    )
                    structured_findings = []
                    for f in (getattr(syn, "findings", []) or [])[:8]:
                        structured_findings.append(
                            {
                                "statement": getattr(f, "statement", str(f)),
                                "confidence": getattr(f, "confidence", 0.80),
                                "confidence_label": getattr(f, "confidence_label", "High"),
                                "claim_ids": getattr(f, "claim_ids", []),
                            }
                        )

                    # Top claims for evidence tracing
                    top_claims = []
                    for c in sorted(
                        claims, key=lambda x: getattr(x, "confidence", 0), reverse=True
                    )[:10]:
                        top_claims.append(
                            {
                                "id": getattr(c, "id", ""),
                                "text": getattr(c, "text", ""),
                                "confidence": round(getattr(c, "confidence", 0.80), 4),
                                "quote": getattr(c, "quote", ""),
                            }
                        )

                    rich_intel_payload = {
                        "run_id": run_id,
                        "objective": run.objective,
                        "domain": domain,
                        "outcome": str(outcome),
                        "executive_answer": direct_ans,
                        "findings": structured_findings,
                        "top_claims": top_claims,
                        "overall_confidence": getattr(syn, "overall_confidence_label", "High")
                        if syn
                        else "Moderate",
                        "sources_count": len(all_ingested),
                        "sources": [
                            {
                                "title": source.title or "",
                                "url": source.location,
                                "domain": source.domain or "",
                                "publisher": source.publisher or "",
                                "published_at": source.published_at.isoformat()
                                if source.published_at
                                else "",
                                "trust_tier": getattr(
                                    source.trust_tier, "value", source.trust_tier
                                ),
                            }
                            for source, _document, _chunks in all_ingested[:20]
                        ],
                        "claims_count": len(claims),
                        "usd_cost": round(run.usd_cost or 0, 6),
                        "completed_at": datetime.now(UTC).isoformat(),
                    }

                    # Text summary for legacy webhook fields
                    findings_snip = (
                        "\n".join(f"• {f['statement']}" for f in structured_findings)
                        if structured_findings
                        else "No structured findings."
                    )
                    finding_text = (
                        f"RESEARCH OBJECTIVE: {run.objective}\n\n"
                        f"EXECUTIVE ANSWER:\n{direct_ans}\n\n"
                        f"KEY FINDINGS ({len(structured_findings)}):\n{findings_snip}\n\n"
                        f"EVIDENCE: {len(claims)} claims from {len(all_ingested)} sources"
                    )

                    # Delivery is external HTTP with its own budget; the writer
                    # lock must not span it.
                    run = await release_writer_lock(session, run)
                    delivery_outcomes = await _dispatch_external_research(
                        run_id=run_id,
                        objective=run.objective,
                        finding_text=finding_text,
                        domain=domain,
                        evidence_count=len(all_ingested),
                        claims_count=len(claims),
                        tags=["intelx", "research", domain, str(target_agent).lower()],
                        extra_context=rich_intel_payload,
                        confidence=(
                            rich_intel_payload.get("overall_confidence", 0.80)
                            if isinstance(rich_intel_payload.get("overall_confidence"), float)
                            else 0.80
                        ),
                    )
                    logger.info(
                        "IntelX ecosystem attempts completed for run %s: %s",
                        run_id,
                        {
                            name: value.get("status", "unknown")
                            for name, value in delivery_outcomes.items()
                        },
                    )
                except Exception as ex:
                    logger.warning(
                        f"Failed to dispatch external ecosystem webhooks: {ex}", exc_info=True
                    )

            return run

        except asyncio.CancelledError:
            logger.info(f"Run {run_id} cancellation acknowledged.")
            previous_status = run.status
            settled = await self._settle_terminal_state(
                session, run_id, RunStatus.CANCELLED, RunOutcome.CANCELLED
            )
            if settled is not None:
                await emit_stage_changed(session, run_id, previous_status, RunStatus.CANCELLED)
                return settled
            return run

        except BudgetExceededError as e:
            logger.error(f"Run {run_id} aborted on budget constraint: {e}")
            settled = await self._settle_terminal_state(
                session,
                run_id,
                RunStatus.FAILED,
                RunOutcome.FAILED,
                {"error": str(e), "type": type(e).__name__},
            )
            return settled if settled is not None else run

        except Exception as e:
            logger.exception(f"Unhandled error during run {run_id} execution: {e}")
            failure = {"error": str(e), "type": type(e).__name__}
            if isinstance(e, ProviderError) and e.details:
                failure["details"] = e.details
            settled = await self._settle_terminal_state(
                session,
                run_id,
                RunStatus.FAILED,
                RunOutcome.FAILED,
                failure,
            )
            if settled is None:
                return run
            await emit_event(session, run_id, "run.failed", failure)
            return settled
