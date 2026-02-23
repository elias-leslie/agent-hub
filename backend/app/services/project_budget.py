"""Per-project cost budget enforcement backed by Redis counters.

Tracks daily and monthly cost accumulation per project and enforces
budget limits configured in the ProjectPermission model.

Fail-CLOSED on errors: budget enforcement is a security/cost gate.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as aioredis
from sqlalchemy import select

from app.config import settings

logger = logging.getLogger(__name__)

# Redis key patterns
_DAILY_KEY = "budget:daily:{project_id}:{date}"  # daily cost accumulator
_MONTHLY_KEY = "budget:monthly:{project_id}:{month}"  # monthly cost accumulator

# TTLs (seconds) — slightly longer than the window to handle edge cases
_DAY_TTL = 90000  # 25 hours
_MONTH_TTL = 2764800  # 32 days

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    """Get or create async Redis client for budget tracking."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.agent_hub_redis_url, decode_responses=True)
    return _redis


@dataclass
class BudgetCheckResult:
    """Result of a project budget check."""

    allowed: bool
    reason: str | None
    daily_usage_usd: float
    monthly_usage_usd: float
    daily_limit_usd: float | None
    monthly_limit_usd: float | None
    alert_level: str | None  # None, "warning", "critical"


async def check_project_budget(project_id: str, db: "AsyncSession | None" = None) -> BudgetCheckResult:
    """Check if project is within budget. Fail-CLOSED on errors.

    Args:
        project_id: The project identifier.
        db: Optional database session. If not provided, creates one.

    Returns:
        BudgetCheckResult with allowed status, usage, and alert level.
    """
    try:
        # 1. Get budget limits from DB
        from app.db import async_session
        from app.models.project_permission import ProjectPermission

        if db is not None:
            result = await db.execute(
                select(ProjectPermission).where(ProjectPermission.project_id == project_id)
            )
            perm = result.scalar_one_or_none()
        else:
            async with async_session() as fresh_db:
                result = await fresh_db.execute(
                    select(ProjectPermission).where(ProjectPermission.project_id == project_id)
                )
                perm = result.scalar_one_or_none()

        if perm is None:
            # Unknown project — fail closed
            return BudgetCheckResult(
                allowed=False,
                reason=f"no permission record for project '{project_id}'",
                daily_usage_usd=0.0,
                monthly_usage_usd=0.0,
                daily_limit_usd=None,
                monthly_limit_usd=None,
                alert_level=None,
            )

        daily_limit = perm.daily_cost_budget_usd
        monthly_limit = perm.monthly_cost_budget_usd
        alert_threshold = perm.budget_alert_threshold

        # 2. If both limits are None, return allowed with no limits
        if daily_limit is None and monthly_limit is None:
            return BudgetCheckResult(
                allowed=True,
                reason=None,
                daily_usage_usd=0.0,
                monthly_usage_usd=0.0,
                daily_limit_usd=None,
                monthly_limit_usd=None,
                alert_level=None,
            )

        # 3. Get current daily/monthly usage from Redis
        r = _get_redis()
        now = datetime.now(UTC)
        date_str = now.strftime("%Y%m%d")
        month_str = now.strftime("%Y%m")

        daily_key = _DAILY_KEY.format(project_id=project_id, date=date_str)
        monthly_key = _MONTHLY_KEY.format(project_id=project_id, month=month_str)

        daily_usage = float(await r.get(daily_key) or 0)
        monthly_usage = float(await r.get(monthly_key) or 0)

        # 4. Check if either limit exceeded
        if daily_limit is not None and daily_usage >= daily_limit:
            return BudgetCheckResult(
                allowed=False,
                reason=f"daily budget exceeded: ${daily_usage:.4f} >= ${daily_limit:.4f}",
                daily_usage_usd=daily_usage,
                monthly_usage_usd=monthly_usage,
                daily_limit_usd=daily_limit,
                monthly_limit_usd=monthly_limit,
                alert_level="critical",
            )

        if monthly_limit is not None and monthly_usage >= monthly_limit:
            return BudgetCheckResult(
                allowed=False,
                reason=f"monthly budget exceeded: ${monthly_usage:.4f} >= ${monthly_limit:.4f}",
                daily_usage_usd=daily_usage,
                monthly_usage_usd=monthly_usage,
                daily_limit_usd=daily_limit,
                monthly_limit_usd=monthly_limit,
                alert_level="critical",
            )

        # 5. Calculate alert_level based on budget_alert_threshold
        alert_level = _calculate_alert_level(
            daily_usage, daily_limit, monthly_usage, monthly_limit, alert_threshold
        )

        return BudgetCheckResult(
            allowed=True,
            reason=None,
            daily_usage_usd=daily_usage,
            monthly_usage_usd=monthly_usage,
            daily_limit_usd=daily_limit,
            monthly_limit_usd=monthly_limit,
            alert_level=alert_level,
        )

    except Exception as e:
        # Fail-CLOSED: budget enforcement is a cost gate
        logger.error(f"Budget check error for project={project_id}: {e}")
        return BudgetCheckResult(
            allowed=False,
            reason=f"budget check error: {e}",
            daily_usage_usd=0.0,
            monthly_usage_usd=0.0,
            daily_limit_usd=None,
            monthly_limit_usd=None,
            alert_level=None,
        )


def _calculate_alert_level(
    daily_usage: float,
    daily_limit: float | None,
    monthly_usage: float,
    monthly_limit: float | None,
    alert_threshold: float,
) -> str | None:
    """Calculate alert level based on usage ratios and threshold.

    Returns:
        None if under threshold, "warning" at threshold, "critical" at 95%.
    """
    max_ratio = 0.0

    if daily_limit is not None and daily_limit > 0:
        max_ratio = max(max_ratio, daily_usage / daily_limit)

    if monthly_limit is not None and monthly_limit > 0:
        max_ratio = max(max_ratio, monthly_usage / monthly_limit)

    if max_ratio >= 0.95:
        return "critical"
    if max_ratio >= alert_threshold:
        return "warning"
    return None


async def record_project_cost(project_id: str, cost_usd: float) -> None:
    """Record cost after completion. Increments daily + monthly counters.

    Fails silently on error (cost already recorded in CostLog).

    Args:
        project_id: The project identifier.
        cost_usd: Cost in USD to record.
    """
    if cost_usd <= 0:
        return

    try:
        r = _get_redis()
        now = datetime.now(UTC)
        date_str = now.strftime("%Y%m%d")
        month_str = now.strftime("%Y%m")

        daily_key = _DAILY_KEY.format(project_id=project_id, date=date_str)
        monthly_key = _MONTHLY_KEY.format(project_id=project_id, month=month_str)

        # Increment daily counter
        daily_new = await r.incrbyfloat(daily_key, cost_usd)
        # Set TTL on first increment (approximate: check if new total ≈ cost)
        if abs(daily_new - cost_usd) < 0.0001:
            await r.expire(daily_key, _DAY_TTL)

        # Increment monthly counter
        monthly_new = await r.incrbyfloat(monthly_key, cost_usd)
        if abs(monthly_new - cost_usd) < 0.0001:
            await r.expire(monthly_key, _MONTH_TTL)

        logger.debug(
            f"Budget: recorded ${cost_usd:.6f} for project={project_id}, "
            f"daily=${daily_new:.6f}, monthly=${monthly_new:.6f}"
        )

    except Exception as e:
        # Fail silently — cost is already recorded in CostLog
        logger.error(f"Redis error recording project cost for project={project_id}: {e}")


async def get_project_budget_usage(project_id: str) -> dict:
    """Get current budget usage for display.

    Args:
        project_id: The project identifier.

    Returns:
        Dictionary with project budget usage details.
    """
    try:
        from app.db import async_session
        from app.models.project_permission import ProjectPermission

        # Get limits from DB
        async with async_session() as db:
            result = await db.execute(
                select(ProjectPermission).where(ProjectPermission.project_id == project_id)
            )
            perm = result.scalar_one_or_none()

        daily_limit = perm.daily_cost_budget_usd if perm else None
        monthly_limit = perm.monthly_cost_budget_usd if perm else None
        alert_threshold = perm.budget_alert_threshold if perm else 0.8

        # Get current usage from Redis
        r = _get_redis()
        now = datetime.now(UTC)
        date_str = now.strftime("%Y%m%d")
        month_str = now.strftime("%Y%m")

        daily_key = _DAILY_KEY.format(project_id=project_id, date=date_str)
        monthly_key = _MONTHLY_KEY.format(project_id=project_id, month=month_str)

        daily_used = float(await r.get(daily_key) or 0)
        monthly_used = float(await r.get(monthly_key) or 0)

        daily_remaining = (daily_limit - daily_used) if daily_limit is not None else None
        monthly_remaining = (monthly_limit - monthly_used) if monthly_limit is not None else None

        alert_level = _calculate_alert_level(
            daily_used, daily_limit, monthly_used, monthly_limit, alert_threshold
        )

        return {
            "project_id": project_id,
            "daily": {
                "used": daily_used,
                "limit": daily_limit,
                "remaining": daily_remaining,
            },
            "monthly": {
                "used": monthly_used,
                "limit": monthly_limit,
                "remaining": monthly_remaining,
            },
            "alert_level": alert_level,
        }

    except Exception as e:
        logger.error(f"Error getting budget usage for project={project_id}: {e}")
        return {
            "project_id": project_id,
            "daily": {"used": 0.0, "limit": None, "remaining": None},
            "monthly": {"used": 0.0, "limit": None, "remaining": None},
            "alert_level": None,
        }


async def invalidate_budget_cache(project_id: str) -> None:
    """Call when budget limits are updated via API.

    Clears any cached budget data for the project.

    Args:
        project_id: The project identifier.
    """
    try:
        r = _get_redis()
        now = datetime.now(UTC)
        date_str = now.strftime("%Y%m%d")
        month_str = now.strftime("%Y%m")

        # Delete current day/month keys to force re-read from DB
        daily_key = _DAILY_KEY.format(project_id=project_id, date=date_str)
        monthly_key = _MONTHLY_KEY.format(project_id=project_id, month=month_str)

        await r.delete(daily_key, monthly_key)
        logger.debug(f"Budget: invalidated cache for project={project_id}")

    except Exception as e:
        logger.error(f"Redis error invalidating budget cache for project={project_id}: {e}")
