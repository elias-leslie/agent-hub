"""Distribution queries: tier and scope breakdowns for active memories."""

from collections import defaultdict

from sqlalchemy import func, select

from app.db import async_session
from app.models.memory_unified import Memory

from .analytics_models import ScopeDistribution, TierDistribution
from .repository import TIER_REVERSE

_TIER_NAMES = TIER_REVERSE  # {1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}


async def get_tier_distribution(group_id: str | None = None) -> list[TierDistribution]:
    """Get distribution of memories across injection tiers."""
    stmt = (
        select(Memory.tier, func.count(Memory.id).label("cnt"))
        .where(Memory.status == "active")
        .group_by(Memory.tier)
        .order_by(func.count(Memory.id).desc())
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    total = sum(cnt for _, cnt in rows)
    return [
        TierDistribution(
            tier=_TIER_NAMES.get(tier_num, "unknown"),
            count=cnt,
            percentage=round(cnt / total * 100, 1) if total > 0 else 0.0,
        )
        for tier_num, cnt in rows
    ]


async def get_scope_distribution(group_id: str | None = None) -> list[ScopeDistribution]:
    """Get distribution of memories across scopes (global/project)."""
    stmt = (
        select(Memory.scope, func.count(Memory.id).label("cnt"))
        .where(Memory.status == "active")
        .group_by(Memory.scope)
        .order_by(func.count(Memory.id).desc())
    )
    if group_id:
        stmt = stmt.where(Memory.group_id == group_id)

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    scope_counts: dict[str, int] = defaultdict(int)
    for scope_val, cnt in rows:
        key = "project" if (scope_val and scope_val.startswith("project:")) else "global"
        scope_counts[key] += cnt

    total = sum(scope_counts.values())
    return [
        ScopeDistribution(
            scope=scope,
            count=count,
            percentage=round(count / total * 100, 1) if total > 0 else 0.0,
        )
        for scope, count in sorted(scope_counts.items(), key=lambda x: x[1], reverse=True)
    ]
