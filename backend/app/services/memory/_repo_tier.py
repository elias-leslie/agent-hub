"""Tier management and triggered references sub-repository for memories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_MAP
from .lifecycle_score import TIER_CONFIGS


def _demotion_reason(
    mem: Memory,
    *,
    harmful_threshold: int,
    ghost_ratio_threshold: float,
    ghost: float,
) -> str | None:
    """Return demotion reason string or None if memory doesn't qualify.

    lifecycle_score is the authoritative ranking (the plan's "lifecycle-ranked,
    not blind" guard). A healthy score — at or above the per-tier demotion
    threshold (lifecycle_score.TIER_CONFIGS) — protects a memory from ghost-ratio
    demotion: mandates inject every session, so a high ghost ratio is structural,
    not a low-value signal, and the multi-factor lifecycle score already folds in
    citation rate. A genuinely dead memory still scores low and is demoted.
    Harmful feedback demotes regardless of score; a missing score (None) leaves
    the blind ghost signal in force.
    """
    if mem.harmful_count >= harmful_threshold:
        return f"harmful_count={mem.harmful_count}"
    cfg = TIER_CONFIGS.get(mem.injection_tier, TIER_CONFIGS["reference"])
    score = mem.lifecycle_score
    if score is not None and score >= cfg.demotion_threshold:
        return None
    if ghost >= ghost_ratio_threshold:
        return f"ghost_ratio={ghost:.1f}"
    if score is not None:
        return f"lifecycle_score={score:.3f}"
    return None


def _promotion_reason(
    mem: Memory,
    *,
    helpful_threshold: int,
) -> str | None:
    """Return promotion reason string or None if memory doesn't qualify.

    Score-based promotion compares lifecycle_score against the per-tier
    promotion threshold (lifecycle_score.TIER_CONFIGS); None never promotes.
    """
    if mem.helpful_count >= helpful_threshold:
        return f"helpful_count={mem.helpful_count}"
    score = mem.lifecycle_score
    if score is not None:
        cfg = TIER_CONFIGS.get(mem.injection_tier, TIER_CONFIGS["reference"])
        if score >= cfg.promotion_threshold:
            return f"lifecycle_score={score:.3f}"
    return None


class TierRepository:
    """Handles tier optimization and trigger-based lookups."""

    async def find_demotion_candidates(
        self,
        *,
        min_loads: int = 200,
        grace_period_hours: int = 48,
        min_age_days: int = 7,
        harmful_threshold: int = 3,
        ghost_ratio_threshold: float = 10.0,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Find memories eligible for tier demotion."""
        now = datetime.now(UTC)
        cutoff_grace = now - timedelta(hours=grace_period_hours)
        cutoff_age = now - timedelta(days=min_age_days)

        stmt = select(Memory).where(
            Memory.status == "active",
            Memory.tier.in_([1, 2, 3]),
            Memory.pinned == False,  # noqa: E712
            Memory.created_at < cutoff_grace,
            or_(
                and_(Memory.loaded_count >= min_loads, Memory.created_at < cutoff_age),
                Memory.harmful_count >= harmful_threshold,
            ),
        )

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
                session.expunge_all()

        candidates = []
        for mem in rows:
            utility = mem.utility_score
            ghost = mem.loaded_count / (mem.referenced_count + 1)
            reason = _demotion_reason(
                mem,
                harmful_threshold=harmful_threshold,
                ghost_ratio_threshold=ghost_ratio_threshold,
                ghost=ghost,
            )
            if reason is None:
                continue
            candidates.append({
                "uuid": str(mem.id),
                "name": mem.name,
                "injection_tier": mem.injection_tier,
                "loaded_count": mem.loaded_count,
                "referenced_count": mem.referenced_count,
                "helpful_count": mem.helpful_count,
                "harmful_count": mem.harmful_count,
                "utility_score": utility,
                "ghost_ratio": ghost,
                "lifecycle_score": mem.lifecycle_score,
                "reason": reason,
            })
        return candidates

    async def find_promotion_candidates(
        self,
        *,
        min_refs: int = 20,
        min_age_days: int = 7,
        helpful_threshold: int = 5,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Find memories eligible for tier promotion."""
        cutoff_age = datetime.now(UTC) - timedelta(days=min_age_days)

        stmt = select(Memory).where(
            Memory.status == "active",
            Memory.tier.in_([2, 3]),
            or_(
                and_(Memory.referenced_count >= min_refs, Memory.created_at < cutoff_age),
                Memory.helpful_count >= helpful_threshold,
            ),
        )

        if db:
            result = await db.execute(stmt)
            rows = list(result.scalars().all())
        else:
            async with async_session() as session:
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
                session.expunge_all()

        candidates = []
        for mem in rows:
            utility = mem.utility_score
            reason = _promotion_reason(
                mem,
                helpful_threshold=helpful_threshold,
            )
            if reason is None:
                continue
            candidates.append({
                "uuid": str(mem.id),
                "name": mem.name,
                "injection_tier": mem.injection_tier,
                "loaded_count": mem.loaded_count,
                "referenced_count": mem.referenced_count,
                "helpful_count": mem.helpful_count,
                "harmful_count": mem.harmful_count,
                "utility_score": utility,
                "lifecycle_score": mem.lifecycle_score,
                "reason": reason,
            })
        return candidates

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
