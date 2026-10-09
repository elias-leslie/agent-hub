"""Reconcile evidence and deterministic maintenance through the existing schedule."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def reconcile_maintenance(db: AsyncSession, *, actor: str = "system:context-maintenance", repair: bool = True) -> dict[str, Any]:
    """Retained historical entry point; automatic maintenance is retired."""
    from app.services.curator_retirement import curator_unavailable

    curator_unavailable()
