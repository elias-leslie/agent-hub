"""Auditable per-memory review inventory."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_unified import Memory

from ._review_agent_prompt import REVIEW_CHECK_KEYS
from .repository import TIER_REVERSE


async def collect_memory_review_inventory(db: AsyncSession) -> dict[str, Any]:
    """Return one immutable snapshot row for every active memory."""
    result = await db.execute(
        select(Memory)
        .where(Memory.status == "active")
        .order_by(Memory.scope, Memory.scope_id, Memory.id)
    )
    rows: list[dict[str, Any]] = []
    for memory in result.scalars().all():
        metadata = dict(memory.metadata_ or {})
        last_review = dict(metadata.get("last_review") or {})
        checks = dict(last_review.get("checks") or {})
        checks_complete = all(
            checks.get(key) in {"pass", "concern", "unknown", "not_applicable"}
            for key in REVIEW_CHECK_KEYS
        )
        rows.append(
            {
                "uuid": str(memory.id),
                "uuid8": memory.uuid_short,
                "name": memory.name,
                "scope": memory.scope,
                "scope_id": memory.scope_id,
                "context_kind": memory.context_kind,
                "authority": TIER_REVERSE.get(int(memory.tier or 0), "reference"),
                "review_status": memory.review_status,
                "reviewed_at": memory.last_reviewed_at,
                "decision": last_review.get("decision"),
                "reason": last_review.get("reason"),
                "checks": checks,
                "applied_remediations": list(last_review.get("applied_remediations") or []),
                "prompt_migration_required": bool(
                    last_review.get("prompt_migration_required")
                ),
                "review_complete": bool(memory.last_reviewed_at and checks_complete),
                "content_chars": len(" ".join((memory.content or "").split())),
                "compact_status": metadata.get("compact_status"),
                "compact_chars": len(str(metadata.get("compact_content") or "")),
            }
        )
    complete_count = sum(bool(row["review_complete"]) for row in rows)
    return {
        "active_count": len(rows),
        "review_complete_count": complete_count,
        "review_incomplete_count": len(rows) - complete_count,
        "clean_count": sum(row["review_status"] == "clean" for row in rows),
        "needs_action_count": sum(row["review_status"] == "needs_action" for row in rows),
        "pending_count": sum(row["review_status"] == "pending" for row in rows),
        "prompt_migration_required_count": sum(
            bool(row["prompt_migration_required"]) for row in rows
        ),
        "items": rows,
    }


__all__ = ["collect_memory_review_inventory"]
