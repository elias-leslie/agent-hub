"""Memory bulk operations endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from .memory_bulk_ops_helpers import (
    build_batch_update_results,
    resolve_batch_updates,
    resolve_ids_with_errors,
    resolve_uuids_tracking_missing,
)
from .memory_schemas import (
    BatchGetRequest,
    BatchGetResponse,
    BatchUpdateRequest,
    BatchUpdateResponse,
    BulkDeleteError,
    BulkDeleteRequest,
    BulkDeleteResponse,
    CleanupResponse,
    EpisodeDetailResponse,
    OrphanedCleanupResponse,
)

router = APIRouter()


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_episodes(
    request: BulkDeleteRequest,
) -> BulkDeleteResponse:
    """Delete multiple episodes from memory.

    Accepts both full UUIDs and 8-character prefixes.
    Returns counts of successful and failed deletions.
    """
    from app.services.memory import get_memory_service
    from app.services.memory.service import MemoryScope

    try:
        memory = get_memory_service(MemoryScope.GLOBAL, None)
        resolved_ids, resolution_errors = await resolve_ids_with_errors(request.ids)
        result = await memory.bulk_delete(resolved_ids)
        all_errors = resolution_errors + result["errors"]
        return BulkDeleteResponse(
            deleted=result["deleted"],
            failed=result["failed"] + len(resolution_errors),
            errors=[BulkDeleteError(**e) for e in all_errors],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk delete failed: {e}") from e


@router.post("/batch-get", response_model=BatchGetResponse)
async def batch_get_episodes(
    request: BatchGetRequest,
) -> BatchGetResponse:
    """Get multiple episodes in a single request.

    Accepts both full UUIDs and 8-character prefixes.
    Returns a map of UUID to episode details; missing UUIDs listed separately.
    """
    from app.services.memory import get_memory_service
    from app.services.memory.service import MemoryScope

    try:
        memory = get_memory_service(MemoryScope.GLOBAL, None)
        resolved_uuids, unresolved = await resolve_uuids_tracking_missing(request.uuids)
        results = await memory.batch_get_episodes(resolved_uuids)
        episodes = {uuid: EpisodeDetailResponse(**data) for uuid, data in results.items()}
        missing = unresolved + [uuid for uuid in resolved_uuids if uuid not in results]
        return BatchGetResponse(episodes=episodes, found=len(episodes), missing=missing)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch get failed: {e}") from e


@router.post("/batch-update", response_model=BatchUpdateResponse)
async def batch_update_episodes(
    request: BatchUpdateRequest,
) -> BatchUpdateResponse:
    """Update properties for multiple episodes in a single request.

    Supports updating: injection_tier, summary, trigger_task_types, pinned,
    auto_inject, display_order. Only provided fields are updated (partial update).
    """
    from app.services.memory.episode_properties import batch_update_episode_properties

    resolved_updates, resolution_errors = await resolve_batch_updates(request.updates)
    update_results: dict[str, bool] = {}
    if resolved_updates:
        update_results = await batch_update_episode_properties(resolved_updates)
    results = build_batch_update_results(resolved_updates, update_results, resolution_errors)
    updated = sum(1 for r in results if r.success)
    return BatchUpdateResponse(
        results=results,
        updated=updated,
        failed=len(results) - updated,
        total=len(results),
    )


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_stale_memories(
    ttl_days: Annotated[int, Query(ge=1, le=365, description="TTL in days")] = 30,
) -> CleanupResponse:
    """Clean up memories not accessed within TTL period.

    Has system activity safeguard: skips cleanup if system has been
    inactive for the same period to prevent accidental mass deletion.
    """
    from app.services.memory import get_memory_service
    from app.services.memory.service import MemoryScope

    try:
        memory = get_memory_service(MemoryScope.GLOBAL, None)
        result = await memory.cleanup_stale_memories(ttl_days=ttl_days)
        return CleanupResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {e}") from e


@router.post("/cleanup-orphaned", response_model=OrphanedCleanupResponse)
async def cleanup_orphaned_edges() -> OrphanedCleanupResponse:
    """Clean up edges with stale episode references.

    Graphiti's remove_episode only removes edges where the deleted episode
    is the FIRST in the episodes[] list. This cleanup handles orphaned
    edges left behind when episodes are deleted.
    """
    from app.services.memory import get_memory_service
    from app.services.memory.service import MemoryScope

    try:
        memory = get_memory_service(MemoryScope.GLOBAL, None)
        result = await memory.cleanup_orphaned_edges()
        return OrphanedCleanupResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Orphaned cleanup failed: {e}") from e
