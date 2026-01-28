#!/usr/bin/env python3
"""One-time cleanup script for test request logs.

Removes historical test/development request logs that pollute metrics:
- Requests with request_source containing 'test'
- Requests with null request_source and status >= 400
- Only removes entries before the cutoff date

Usage:
    cd ~/agent-hub/backend
    .venv/bin/python scripts/cleanup_test_logs.py --dry-run  # Preview
    .venv/bin/python scripts/cleanup_test_logs.py            # Execute
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, func, or_, select, and_
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import RequestLog


# Cutoff: only delete entries before this timestamp
CUTOFF_DATE = datetime(2026, 1, 28, 12, 0, 0, tzinfo=timezone.utc)


async def get_db_url() -> str:
    """Get database URL from environment."""
    from dotenv import load_dotenv

    # Load from ~/.env.local
    env_file = os.path.expanduser("~/.env.local")
    if os.path.exists(env_file):
        load_dotenv(env_file)

    db_url = os.getenv("AGENT_HUB_DB_URL")
    if not db_url:
        raise ValueError("AGENT_HUB_DB_URL not set in environment")

    # Convert to async URL if needed
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return db_url


async def count_entries_to_delete(session: AsyncSession) -> dict[str, int]:
    """Count entries that would be deleted."""
    # Test entries (request_source contains 'test')
    test_count = await session.scalar(
        select(func.count(RequestLog.id)).where(
            and_(
                RequestLog.request_source.ilike("%test%"),
                RequestLog.created_at < CUTOFF_DATE,
            )
        )
    )

    # Null source with errors
    null_error_count = await session.scalar(
        select(func.count(RequestLog.id)).where(
            and_(
                RequestLog.request_source.is_(None),
                RequestLog.status_code >= 400,
                RequestLog.created_at < CUTOFF_DATE,
            )
        )
    )

    # Historical development errors from known sources
    dev_error_count = await session.scalar(
        select(func.count(RequestLog.id)).where(
            and_(
                RequestLog.request_source.in_(["summitflow", "claude-code"]),
                RequestLog.status_code >= 400,
                RequestLog.created_at < CUTOFF_DATE,
            )
        )
    )

    return {
        "test_entries": test_count or 0,
        "null_error_entries": null_error_count or 0,
        "dev_error_entries": dev_error_count or 0,
        "total": (test_count or 0) + (null_error_count or 0) + (dev_error_count or 0),
    }


async def delete_test_entries(session: AsyncSession, dry_run: bool) -> int:
    """Delete test request log entries."""
    if dry_run:
        return 0

    result = await session.execute(
        delete(RequestLog).where(
            and_(
                RequestLog.request_source.ilike("%test%"),
                RequestLog.created_at < CUTOFF_DATE,
            )
        )
    )
    return result.rowcount


async def delete_null_error_entries(session: AsyncSession, dry_run: bool) -> int:
    """Delete entries with null source and error status."""
    if dry_run:
        return 0

    result = await session.execute(
        delete(RequestLog).where(
            and_(
                RequestLog.request_source.is_(None),
                RequestLog.status_code >= 400,
                RequestLog.created_at < CUTOFF_DATE,
            )
        )
    )
    return result.rowcount


async def delete_dev_error_entries(session: AsyncSession, dry_run: bool) -> int:
    """Delete historical development errors from known sources."""
    if dry_run:
        return 0

    result = await session.execute(
        delete(RequestLog).where(
            and_(
                RequestLog.request_source.in_(["summitflow", "claude-code"]),
                RequestLog.status_code >= 400,
                RequestLog.created_at < CUTOFF_DATE,
            )
        )
    )
    return result.rowcount


async def main(dry_run: bool = True) -> None:
    """Run the cleanup."""
    db_url = await get_db_url()
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print(f"Cleanup target: entries before {CUTOFF_DATE.isoformat()}")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'EXECUTE (will delete)'}")
    print()

    async with async_session() as session:
        # Count what would be deleted
        counts = await count_entries_to_delete(session)
        print(f"Entries to delete:")
        print(f"  - Test entries (request_source ~ 'test'): {counts['test_entries']}")
        print(f"  - Null source + error status: {counts['null_error_entries']}")
        print(f"  - Dev errors (summitflow/claude-code): {counts['dev_error_entries']}")
        print(f"  - Total: {counts['total']}")
        print()

        if counts["total"] == 0:
            print("Nothing to delete.")
            return

        if dry_run:
            print("Run without --dry-run to execute deletion.")
            return

        # Execute deletions
        test_deleted = await delete_test_entries(session, dry_run)
        null_deleted = await delete_null_error_entries(session, dry_run)
        dev_deleted = await delete_dev_error_entries(session, dry_run)

        await session.commit()

        print(f"Deleted:")
        print(f"  - Test entries: {test_deleted}")
        print(f"  - Null error entries: {null_deleted}")
        print(f"  - Dev error entries: {dev_deleted}")
        print(f"  - Total: {test_deleted + null_deleted + dev_deleted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean up test request logs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without making changes",
    )
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run))
