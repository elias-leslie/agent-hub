"""
Unified memory client — replaces graphiti_client.py.

Central entry point for all memory operations. Uses PostgreSQL + pgvector
instead of Neo4j/Graphiti.
"""

from __future__ import annotations

import logging

from app.services.memory.embedder import EmbedderService, get_embedder
from app.services.memory.repository import MemoryRepository, get_memory_repository

logger = logging.getLogger(__name__)

# Re-export core components
__all__ = [
    "EmbedderService",
    "MemoryRepository",
    "get_embedder",
    "get_memory_repository",
    "init_memory_schema",
]

# Embedding configuration (same values used by former Graphiti integration)
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768


async def init_memory_schema() -> None:
    """Initialize memory schema — no-op for PostgreSQL (handled by Alembic migrations)."""
    logger.info("Memory schema initialized (PostgreSQL + pgvector via Alembic)")


# ── Backward-compat shims for graphiti_client.py imports ──────────────

# These functions previously operated on Neo4j Episodic nodes.
# Now they delegate to MemoryRepository.


async def set_episode_injection_tier(
    episode_uuid: str, tier: str, **_kwargs: object
) -> bool:
    """Set injection tier for a memory (backward compat)."""
    repo = get_memory_repository()
    return await repo.update(episode_uuid, injection_tier=tier)


async def set_episode_pinned(
    episode_uuid: str, pinned: bool, **_kwargs: object
) -> bool:
    """Set pinned flag (backward compat)."""
    repo = get_memory_repository()
    return await repo.update(episode_uuid, pinned=pinned)


async def set_episode_auto_inject(
    episode_uuid: str, auto_inject: bool, **_kwargs: object
) -> bool:
    """Set auto_inject flag (backward compat)."""
    repo = get_memory_repository()
    return await repo.update(episode_uuid, auto_inject=auto_inject)


async def set_episode_display_order(
    episode_uuid: str, display_order: int, **_kwargs: object
) -> bool:
    """Set display order (backward compat)."""
    repo = get_memory_repository()
    return await repo.update(episode_uuid, display_order=display_order)


async def set_episode_trigger_task_types(
    episode_uuid: str, task_types: list[str], **_kwargs: object
) -> bool:
    """Set trigger task types (backward compat)."""
    repo = get_memory_repository()
    return await repo.update(episode_uuid, trigger_task_types=task_types)


async def set_episode_trigger_phases(
    episode_uuid: str, phases: list[str], **_kwargs: object
) -> bool:
    """Set trigger phases (backward compat)."""
    repo = get_memory_repository()
    return await repo.update(episode_uuid, trigger_phases=phases)


async def set_episode_summary(
    episode_uuid: str, summary: str, **_kwargs: object
) -> bool:
    """Set summary (backward compat)."""
    repo = get_memory_repository()
    return await repo.update(episode_uuid, summary=summary)


async def get_episode_properties(
    episode_uuid: str, **_kwargs: object
) -> dict | None:
    """Get episode properties (backward compat)."""
    repo = get_memory_repository()
    return await repo.get_as_dict(episode_uuid)


async def get_triggered_references(
    task_type: str, group_id: str = "global", **_kwargs: object
) -> list[dict]:
    """Get triggered references (backward compat)."""
    repo = get_memory_repository()
    mems = await repo.get_triggered_references(task_type, group_id=group_id)
    return [MemoryRepository._to_dict(m) for m in mems]


async def get_phase_triggered_references(
    phase: str, group_id: str = "global", **_kwargs: object
) -> list[dict]:
    """Get phase-triggered references (backward compat)."""
    repo = get_memory_repository()
    mems = await repo.get_phase_triggered_references(phase, group_id=group_id)
    return [MemoryRepository._to_dict(m) for m in mems]


async def batch_set_episode_injection_tier(
    updates: list[dict], **_kwargs: object
) -> dict[str, bool]:
    """Batch set injection tiers (backward compat)."""
    repo = get_memory_repository()
    results: dict[str, bool] = {}
    for upd in updates:
        uid = upd.get("uuid", "")
        tier = upd.get("tier", "reference")
        try:
            results[uid] = await repo.update(uid, injection_tier=tier)
        except Exception:
            results[uid] = False
    return results


async def batch_update_episode_properties(
    updates: list[dict], **_kwargs: object
) -> dict[str, bool]:
    """Batch update properties (backward compat)."""
    repo = get_memory_repository()
    return await repo.batch_update_properties(updates)


async def init_episode_usage_properties(
    episode_uuid: str, **_kwargs: object
) -> bool:
    """Initialize usage stats to 0 (backward compat — no-op, defaults handle this)."""
    return True


async def copy_episode_stats(
    source_uuid: str, target_uuid: str, **_kwargs: object
) -> bool:
    """Copy stats from source to target memory (backward compat)."""
    repo = get_memory_repository()
    source = await repo.get_as_dict(source_uuid)
    if not source:
        return False
    return await repo.update(
        target_uuid,
        loaded_count=source.get("loaded_count", 0),
        referenced_count=source.get("referenced_count", 0),
        helpful_count=source.get("helpful_count", 0),
        harmful_count=source.get("harmful_count", 0),
    )
