"""Triggered-reference lookups sub-repository for memories."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_MAP


class TriggerRepository:
    """Handles trigger-based reference lookups."""

    async def get_triggered_references(
        self,
        task_type: str,
        *,
        group_id: str = "global",
        scope: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[Memory]:
        """Get reference-tier memories triggered by a task_type."""
        stmt = select(Memory).where(
            Memory.status == "active",
            Memory.tier == TIER_MAP["reference"],
            Memory.trigger_task_types.any(task_type),
        )
        if group_id:
            stmt = stmt.where(Memory.group_id == group_id)
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        stmt = stmt.order_by(Memory.display_order, Memory.created_at.desc())

        if db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
        async with async_session() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            session.expunge_all()
            return rows

    async def get_phase_triggered_references(
        self,
        phase: str,
        *,
        group_id: str = "global",
        scope: str | None = None,
        db: AsyncSession | None = None,
    ) -> list[Memory]:
        """Get reference-tier memories triggered by a subtask phase."""
        stmt = select(Memory).where(
            Memory.status == "active",
            Memory.tier == TIER_MAP["reference"],
            Memory.trigger_phases.any(phase),
        )
        if group_id:
            stmt = stmt.where(Memory.group_id == group_id)
        if scope:
            stmt = stmt.where(Memory.scope == scope)
        stmt = stmt.order_by(Memory.display_order, Memory.created_at.desc())

        if db:
            result = await db.execute(stmt)
            return list(result.scalars().all())
        async with async_session() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            session.expunge_all()
            return rows
