"""INTELX Automated Data Retention and Lifecycle Purging Service."""

import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.enums import RunStatus
from intelx.core.settings import get_settings
from intelx.db.models import (
    Artifact,
    Chunk,
    Claim,
    Document,
    Evidence,
    Finding,
    ResearchRun,
    Source,
)

logger = logging.getLogger(__name__)


async def purge_expired_retention(
    session: AsyncSession,
    raw_docs_retention_days: int | None = None,
    reports_retention_days: int | None = None,
) -> dict[str, int]:
    """Purge raw documents older than raw_docs_retention_days and full runs older than reports_retention_days."""
    settings = get_settings()
    raw_days = (
        raw_docs_retention_days
        if raw_docs_retention_days is not None
        else settings.RETENTION_DAYS_RAW_DOCS
    )
    report_days = (
        reports_retention_days
        if reports_retention_days is not None
        else settings.RETENTION_DAYS_REPORTS
    )

    now = datetime.now(UTC)
    raw_cutoff = now - timedelta(days=raw_days)
    report_cutoff = now - timedelta(days=report_days)

    terminal_statuses = [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED]

    # 1. Purge Full Expired Runs (Older than report_days)
    stmt_old_runs = (
        select(ResearchRun)
        .where(ResearchRun.status.in_(terminal_statuses))
        .where(ResearchRun.created_at < report_cutoff)
    )
    old_runs = list((await session.execute(stmt_old_runs)).scalars().all())
    purged_runs_count = len(old_runs)

    for run in old_runs:
        run_id = run.id
        # Remove on-disk artifact directory if exists
        run_art_dir = Path(settings.DATA_DIR) / "artifacts" / run_id
        if run_art_dir.exists():
            shutil.rmtree(run_art_dir, ignore_errors=True)

        # Delete database records associated with run
        await session.execute(delete(Artifact).where(Artifact.run_id == run_id))
        await session.execute(delete(Finding).where(Finding.run_id == run_id))
        await session.execute(delete(Evidence).where(Evidence.created_by_run_id == run_id))
        await session.execute(delete(Claim).where(Claim.run_id == run_id))
        await session.execute(delete(Source).where(Source.created_by_run_id == run_id))
        await session.execute(delete(ResearchRun).where(ResearchRun.id == run_id))

    # 2. Purge Raw Scraped Documents & Chunks for Runs older than raw_days (Retaining Findings & Reports)
    stmt_raw_runs = (
        select(ResearchRun.id)
        .where(ResearchRun.status.in_(terminal_statuses))
        .where(ResearchRun.created_at < raw_cutoff)
        .where(ResearchRun.created_at >= report_cutoff)
    )
    raw_run_ids = list((await session.execute(stmt_raw_runs)).scalars().all())
    purged_raw_docs_count = 0

    if raw_run_ids:
        # Clear large text body in Document table for space saving while keeping metadata
        stmt_docs = (
            select(Document)
            .join(Source, Document.source_id == Source.id)
            .where(Source.created_by_run_id.in_(raw_run_ids))
        )
        docs = list((await session.execute(stmt_docs)).scalars().all())
        purged_raw_docs_count = len(docs)
        for doc in docs:
            doc.text = "[PURGED_DUE_TO_RETENTION_POLICY]"

        # Remove chunk texts
        doc_ids = [d.id for d in docs]
        if doc_ids:
            stmt_chunks = select(Chunk).where(Chunk.document_id.in_(doc_ids))
            chunks = list((await session.execute(stmt_chunks)).scalars().all())
            for chunk in chunks:
                chunk.text = "[PURGED_DUE_TO_RETENTION_POLICY]"

    await session.commit()
    logger.info(
        f"Retention purge complete: purged {purged_runs_count} expired runs (> {report_days}d), "
        f"cleared {purged_raw_docs_count} raw documents (> {raw_days}d)."
    )

    return {
        "purged_runs_count": purged_runs_count,
        "purged_raw_docs_count": purged_raw_docs_count,
    }
