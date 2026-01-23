"""Session cleanup service.

Provides utilities for archiving and cleaning up legacy and test sessions.
"""

import logging
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session

logger = logging.getLogger(__name__)


# Test project patterns - sessions from these projects are eligible for cleanup
TEST_PROJECT_PATTERNS = [
    "test",
    "test-%",
    "%-test",
    "verify",
    "audit",
    "monkey-fight",
    "phase2-test",
    "gemini-confirm",
]


async def mark_sessions_as_legacy(db: AsyncSession) -> int:
    """Mark all sessions without client_id as legacy.

    Returns:
        Number of sessions marked as legacy.
    """
    result = await db.execute(
        update(Session)
        .where(Session.client_id.is_(None))
        .where(Session.is_legacy.is_(False))
        .values(is_legacy=True)
    )
    await db.commit()
    count = result.rowcount
    logger.info(f"Marked {count} sessions as legacy")
    return count


async def get_legacy_session_stats(db: AsyncSession) -> dict:
    """Get statistics about legacy sessions.

    Returns:
        Dictionary with legacy session statistics.
    """
    # Total legacy sessions
    total_result = await db.execute(
        select(func.count()).where(Session.is_legacy.is_(True))
    )
    total_legacy = total_result.scalar_one()

    # Legacy sessions by project
    by_project_result = await db.execute(
        select(Session.project_id, func.count().label("count"))
        .where(Session.is_legacy.is_(True))
        .group_by(Session.project_id)
        .order_by(func.count().desc())
    )
    by_project = [(row.project_id, row.count) for row in by_project_result]

    # Age distribution
    now = datetime.utcnow()
    age_30d = now - timedelta(days=30)
    age_90d = now - timedelta(days=90)

    old_30d_result = await db.execute(
        select(func.count())
        .where(Session.is_legacy.is_(True))
        .where(Session.created_at < age_30d)
    )
    old_30d = old_30d_result.scalar_one()

    old_90d_result = await db.execute(
        select(func.count())
        .where(Session.is_legacy.is_(True))
        .where(Session.created_at < age_90d)
    )
    old_90d = old_90d_result.scalar_one()

    return {
        "total_legacy": total_legacy,
        "by_project": by_project,
        "older_than_30_days": old_30d,
        "older_than_90_days": old_90d,
    }


async def cleanup_test_sessions(
    db: AsyncSession,
    older_than_days: int = 30,
    dry_run: bool = True,
) -> dict:
    """Delete legacy sessions from test projects.

    Args:
        db: Database session.
        older_than_days: Only delete sessions older than this many days.
        dry_run: If True, only count sessions without deleting.

    Returns:
        Dictionary with cleanup statistics.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)

    # Build project filter - use LIKE patterns for test projects
    project_filters = []
    for pattern in TEST_PROJECT_PATTERNS:
        if "%" in pattern:
            project_filters.append(Session.project_id.like(pattern))
        else:
            project_filters.append(Session.project_id == pattern)

    from sqlalchemy import or_

    # Count sessions to delete
    count_query = (
        select(func.count())
        .where(Session.is_legacy.is_(True))
        .where(Session.created_at < cutoff_date)
        .where(or_(*project_filters))
    )
    count_result = await db.execute(count_query)
    session_count = count_result.scalar_one()

    if dry_run:
        logger.info(f"[DRY RUN] Would delete {session_count} test sessions")
        return {
            "dry_run": True,
            "sessions_to_delete": session_count,
            "older_than_days": older_than_days,
        }

    # Actually delete (messages cascade delete)
    delete_query = (
        delete(Session)
        .where(Session.is_legacy.is_(True))
        .where(Session.created_at < cutoff_date)
        .where(or_(*project_filters))
    )
    result = await db.execute(delete_query)
    await db.commit()

    logger.info(f"Deleted {result.rowcount} test sessions")
    return {
        "dry_run": False,
        "sessions_deleted": result.rowcount,
        "older_than_days": older_than_days,
    }


async def archive_legacy_sessions(
    db: AsyncSession,
    project_id: str,
    older_than_days: int = 90,
    action: Literal["mark", "delete"] = "mark",
) -> dict:
    """Archive legacy sessions from a specific project.

    Args:
        db: Database session.
        project_id: Project to archive sessions from.
        older_than_days: Only process sessions older than this.
        action: "mark" to just mark, "delete" to actually delete.

    Returns:
        Dictionary with archive statistics.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)

    # Count eligible sessions
    count_result = await db.execute(
        select(func.count())
        .where(Session.is_legacy.is_(True))
        .where(Session.project_id == project_id)
        .where(Session.created_at < cutoff_date)
    )
    session_count = count_result.scalar_one()

    if action == "mark":
        logger.info(f"Found {session_count} legacy sessions for {project_id} older than {older_than_days} days")
        return {
            "project_id": project_id,
            "sessions_found": session_count,
            "older_than_days": older_than_days,
            "action": "mark",
        }

    # Delete sessions
    result = await db.execute(
        delete(Session)
        .where(Session.is_legacy.is_(True))
        .where(Session.project_id == project_id)
        .where(Session.created_at < cutoff_date)
    )
    await db.commit()

    logger.info(f"Deleted {result.rowcount} legacy sessions for {project_id}")
    return {
        "project_id": project_id,
        "sessions_deleted": result.rowcount,
        "older_than_days": older_than_days,
        "action": "delete",
    }
