"""Subscription-aware cost accounting (cash vs credits vs utilization vs API-equivalent)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SubscriptionUsageSnapshot

_CREDIT_MODE_TTL_S = 60.0
_credit_mode_cache: tuple[float, bool] = (0.0, False)


async def codex_in_credit_mode(db: AsyncSession) -> bool:
    """True while Codex's weekly included limit is exhausted, so calls draw credits."""
    global _credit_mode_cache
    checked, value = _credit_mode_cache
    if time.monotonic() - checked < _CREDIT_MODE_TTL_S:
        return value
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(SubscriptionUsageSnapshot.used_percent)
            .where(
                SubscriptionUsageSnapshot.provider == "codex",
                SubscriptionUsageSnapshot.window_minutes == 10080,
                SubscriptionUsageSnapshot.resets_at > now,
            )
            .order_by(SubscriptionUsageSnapshot.resets_at.desc(), SubscriptionUsageSnapshot.used_percent.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    value = row is not None and row >= 100.0
    _credit_mode_cache = (time.monotonic(), value)
    return value
