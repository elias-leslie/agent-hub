"""Retired technical recovery dispatch for context maintenance items.

Automatic SummitFlow task dispatch belonged to the retired Memory Curator
workflow. The entry points remain so historical callers get an explicit 410.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import ContextMaintenanceItem


async def dispatch_technical_work(
    db: AsyncSession,
    item: ContextMaintenanceItem,
    *,
    reason: str,
) -> dict[str, Any]:
    """Retired: creating SummitFlow technical recovery tasks is unavailable."""
    from app.services.curator_retirement import curator_unavailable

    curator_unavailable()


async def reconcile_technical_work(db: AsyncSession) -> dict[str, Any]:
    """Retired: observing SummitFlow technical recovery tasks is unavailable."""
    from app.services.curator_retirement import curator_unavailable

    curator_unavailable()


__all__ = ["dispatch_technical_work", "reconcile_technical_work"]
