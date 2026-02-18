"""CRUD operations for component ratings (scorecard system)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scorecard import ComponentRating

logger = logging.getLogger(__name__)


async def store_rating(
    db: AsyncSession,
    session_id: str,
    component_id: str,
    project_id: str,
    *,
    reliability: int | None = None,
    clarity: int | None = None,
    ergonomics: int | None = None,
    integration: int | None = None,
    documentation: int | None = None,
    comment: str | None = None,
    agent_slug: str | None = None,
    model_used: str | None = None,
    session_type: str | None = None,
) -> ComponentRating:
    """Store a single component rating."""
    rating = ComponentRating(
        session_id=session_id,
        component_id=component_id,
        project_id=project_id,
        reliability=reliability,
        clarity=clarity,
        ergonomics=ergonomics,
        integration=integration,
        documentation=documentation,
        comment=comment,
        agent_slug=agent_slug,
        model_used=model_used,
        session_type=session_type,
    )
    db.add(rating)
    return rating


async def store_friction_report(
    db: AsyncSession,
    session_id: str,
    component_id: str,
    project_id: str,
    issue: str,
    severity: str,
    *,
    agent_slug: str | None = None,
    model_used: str | None = None,
    session_type: str | None = None,
) -> ComponentRating:
    """Store a friction report as a partial component rating.

    Friction reports map severity to a low reliability score:
    - high → reliability=1
    - medium → reliability=2
    - low → reliability=3
    """
    severity_to_reliability = {"high": 1, "medium": 2, "low": 3}
    reliability = severity_to_reliability.get(severity, 2)

    return await store_rating(
        db,
        session_id=session_id,
        component_id=component_id,
        project_id=project_id,
        reliability=reliability,
        comment=f"[{severity}] {issue}",
        agent_slug=agent_slug,
        model_used=model_used,
        session_type=session_type,
    )


async def get_session_ratings(
    db: AsyncSession,
    session_id: str,
) -> list[ComponentRating]:
    """Get all ratings for a session."""
    result = await db.execute(
        select(ComponentRating)
        .where(ComponentRating.session_id == session_id)
        .order_by(ComponentRating.created_at)
    )
    return list(result.scalars().all())


async def get_component_averages(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get average ratings per component over a time window.

    Returns list of dicts with component_id, avg_reliability, avg_clarity,
    avg_ergonomics, avg_integration, avg_documentation, rating_count.
    """
    query = text("""
        SELECT
            component_id,
            AVG(reliability)::float AS avg_reliability,
            AVG(clarity)::float AS avg_clarity,
            AVG(ergonomics)::float AS avg_ergonomics,
            AVG(integration)::float AS avg_integration,
            AVG(documentation)::float AS avg_documentation,
            COUNT(*) AS rating_count
        FROM component_ratings
        WHERE created_at >= NOW() - make_interval(days => :days)
        AND (:project_id IS NULL OR project_id = :project_id)
        GROUP BY component_id
        ORDER BY rating_count DESC
    """)
    result = await db.execute(query, {"days": days, "project_id": project_id})
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def get_component_trend(
    db: AsyncSession,
    component_id: str,
    *,
    days: int = 30,
    bucket: str = "day",
) -> list[dict[str, Any]]:
    """Get daily/weekly trend for a component.

    Args:
        component_id: Component to query
        days: Lookback window
        bucket: 'day' or 'week'

    Returns list of dicts with period, avg ratings, count.
    """
    trunc = "day" if bucket == "day" else "week"
    query = text("""
        SELECT
            date_trunc(:trunc, created_at) AS period,
            AVG(reliability)::float AS avg_reliability,
            AVG(clarity)::float AS avg_clarity,
            AVG(ergonomics)::float AS avg_ergonomics,
            AVG(integration)::float AS avg_integration,
            AVG(documentation)::float AS avg_documentation,
            COUNT(*) AS rating_count
        FROM component_ratings
        WHERE component_id = :component_id
        AND created_at >= NOW() - make_interval(days => :days)
        GROUP BY period
        ORDER BY period
    """)
    result = await db.execute(
        query, {"component_id": component_id, "days": days, "trunc": trunc}
    )
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def get_friction_comments(
    db: AsyncSession,
    *,
    component_id: str | None = None,
    project_id: str | None = None,
    days: int = 30,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get recent friction comments (ratings with non-null comment).

    Returns list of dicts with rating details including comment.
    """
    query = text("""
        SELECT
            cr.id,
            cr.session_id,
            cr.component_id,
            cr.comment,
            cr.reliability,
            cr.project_id,
            cr.agent_slug,
            cr.model_used,
            cr.session_type,
            cr.created_at
        FROM component_ratings cr
        WHERE cr.comment IS NOT NULL
        AND cr.created_at >= NOW() - make_interval(days => :days)
        AND (:component_id IS NULL OR cr.component_id = :component_id)
        AND (:project_id IS NULL OR cr.project_id = :project_id)
        ORDER BY cr.created_at DESC
        LIMIT :limit
    """)
    result = await db.execute(
        query,
        {
            "component_id": component_id,
            "project_id": project_id,
            "days": days,
            "limit": limit,
        },
    )
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def get_summary(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """Get aggregated scorecard summary.

    Returns top/bottom components, total ratings, overall averages.
    """
    averages = await get_component_averages(db, project_id=project_id, days=days)

    if not averages:
        return {
            "total_ratings": 0,
            "components_rated": 0,
            "top_components": [],
            "bottom_components": [],
            "overall_avg": None,
        }

    # Compute overall score per component (average of all dimensions)
    for row in averages:
        dims = [
            row.get(f"avg_{d}")
            for d in ("reliability", "clarity", "ergonomics", "integration", "documentation")
            if row.get(f"avg_{d}") is not None
        ]
        row["overall_score"] = sum(dims) / len(dims) if dims else None

    sorted_by_score = sorted(
        [r for r in averages if r.get("overall_score") is not None],
        key=lambda r: r["overall_score"],
        reverse=True,
    )

    total_ratings = sum(r["rating_count"] for r in averages)

    return {
        "total_ratings": total_ratings,
        "components_rated": len(averages),
        "top_components": sorted_by_score[:5],
        "bottom_components": sorted_by_score[-5:][::-1] if len(sorted_by_score) > 5 else [],
        "overall_avg": (
            sum(r["overall_score"] for r in sorted_by_score) / len(sorted_by_score)
            if sorted_by_score
            else None
        ),
    }
