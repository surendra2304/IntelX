"""INTELX Data Retention, Raw Ingestion Purge Engine, and Audit Tracking."""

import asyncio
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from intelx.core.settings import get_settings
from intelx.db.repos import AuditChain
from intelx.db.session import get_sessionmaker

logger = logging.getLogger(__name__)


async def purge_raw_files(
    session: AsyncSession,
    retention_days: int | None = None,
    base_dir: Path | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Purge raw ingestion files older than threshold and log cryptographic audit record."""
    settings = get_settings()
    days = retention_days if retention_days is not None else settings.RAW_RETENTION_DAYS
    cutoff_time = time.time() - (days * 86400)

    raw_dir = base_dir or (Path("./data/raw").resolve())
    purged_count = 0
    bytes_freed = 0
    purged_paths: list[str] = []

    if raw_dir.exists() and raw_dir.is_dir():
        for file_path in raw_dir.rglob("*"):
            if file_path.is_file():
                try:
                    stat = file_path.stat()
                    if stat.st_mtime < cutoff_time:
                        file_size = stat.st_size
                        file_path.unlink()
                        purged_count += 1
                        bytes_freed += file_size
                        purged_paths.append(str(file_path))
                except Exception as ex:
                    logger.warning(f"Failed to purge file {file_path}: {ex}")

    # Record Audit Event
    await AuditChain.append_event(
        session=session,
        actor=actor,
        action="retention.purged",
        object_type="storage",
        object_id="data/raw",
        detail_json={
            "retention_days": days,
            "purged_count": purged_count,
            "bytes_freed": bytes_freed,
            "cutoff_iso": (datetime.now(UTC) - timedelta(days=days)).isoformat(),
        },
    )
    await session.commit()

    return {
        "status": "success",
        "purged_count": purged_count,
        "bytes_freed": bytes_freed,
        "retention_days": days,
    }


async def execute_retention_purge(
    older_than_days: int | None = None,
    reports_days: int | None = None,
) -> dict[str, Any]:
    """Unified entrypoint executing both file and database retention cleanup."""
    from intelx.db.retention import purge_expired_retention

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        file_res = await purge_raw_files(session, retention_days=older_than_days)
        db_res = await purge_expired_retention(
            session=session,
            raw_docs_retention_days=older_than_days,
            reports_retention_days=reports_days,
        )
        return {**file_res, **db_res}


def main():
    """CLI Entrypoint for running retention purge command."""
    args = sys.argv[1:]
    action = args[0] if args else "purge"

    if action == "purge":
        sessionmaker = get_sessionmaker()

        async def _run():
            async with sessionmaker() as session:
                result = await purge_raw_files(session, actor="cli-retention-job")
                print("[INTELX RETENTION] Purge completed successfully:")
                print(f"  - Purged Files: {result['purged_count']}")
                print(f"  - Bytes Freed: {result['bytes_freed']}")
                print(f"  - Retention Threshold: {result['retention_days']} days")

        asyncio.run(_run())
    else:
        print(f"Unknown retention command: '{action}'. Expected 'purge'")
        sys.exit(1)


if __name__ == "__main__":
    main()
