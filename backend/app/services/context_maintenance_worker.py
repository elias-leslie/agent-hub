"""Unavailable entry points for the retired automatic context worker."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.curator_retirement import curator_unavailable


async def _recover_pending(
    db: AsyncSession,
    *,
    batch_limit: int | None = None,
    source_ids: list[str] | None = None,
    review_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Reject legacy automatic recovery before reading or changing state."""
    curator_unavailable()


async def run_context_maintenance(
    db: AsyncSession,
    *,
    batch_limit: int,
    followup_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Reject legacy scheduled maintenance before reading or changing state."""
    curator_unavailable()
