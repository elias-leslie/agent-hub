"""Memory bulk operations endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from app.services.memory.memory_utils import resolve_uuid_prefix
from app.services.memory.types import InjectionTier

from .memory_schemas import (
    BatchGetRequest,
    BatchGetResponse,
    BatchUpdateRequest,
    BatchUpdateResponse,
    BatchUpdateResult,
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
    """
    Delete multiple episodes from memory.

    Accepts both full UUIDs and 8-character prefixes.
    Attempts to delete all provided episode IDs.
    Returns counts of successful and failed deletions.
    """
    from app.services.memory import get_memory_service
    from app.services.memory.service import MemoryScope

    try:
        memory = get_memory_service(MemoryScope.GLOBAL, None)

        # Resolve UUID prefixes to full UUIDs
        resolved_ids: list[str] = []
        resolution_errors: list[dict[str, str]] = []

        for id_or_prefix in request.ids:
            try:
                full_uuid = await resolve_uuid_prefix(id_or_prefix, group_id="global")
                resolved_ids.append(full_uuid)
            except ValueError as e:
                resolution_errors.append({"id": id_or_prefix, "error": str(e)})

        result = await memory.bulk_delete(resolved_ids)

        # Combine resolution errors with delete errors
        all_errors = resolution_errors + result["errors"]

        return BulkDeleteResponse(
            deleted=result["deleted"],
            failed=result["failed"] + len(resolution_errors),
            errors=[BulkDeleteError(**e) for e in all_errors],
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Bulk delete failed: {e}",
        ) from e


@router.post("/batch-get", response_model=BatchGetResponse)
async def batch_get_episodes(
    request: BatchGetRequest,
) -> BatchGetResponse:
    """
    Get multiple episodes in a single request.

    Accepts both full UUIDs and 8-character prefixes (same as single get).
    Efficient batch retrieval for when you need details on multiple episodes.

    Returns a map of UUID to episode details. Missing UUIDs are listed separately.
    """
    from app.services.memory import get_memory_service
    from app.services.memory.service import MemoryScope

    try:
        memory = get_memory_service(MemoryScope.GLOBAL, None)
        # Resolve UUID prefixes to full UUIDs
        resolved_uuids: list[str] = []
        resolution_errors: list[str] = []

        for uuid_or_prefix in request.uuids:
            try:
                full_uuid = await resolve_uuid_prefix(uuid_or_prefix, group_id="global")
                resolved_uuids.append(full_uuid)
            except ValueError:
                # Prefix not found or ambiguous
                resolution_errors.append(uuid_or_prefix)

        results = await memory.batch_get_episodes(resolved_uuids)

        # Convert to response format
        episodes = {uuid: EpisodeDetailResponse(**data) for uuid, data in results.items()}

        # Missing = resolution errors + UUIDs not found in DB
        missing = resolution_errors + [uuid for uuid in resolved_uuids if uuid not in results]

        return BatchGetResponse(
            episodes=episodes,
            found=len(episodes),
            missing=missing,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Batch get failed: {e}",
        ) from e


@router.post("/batch-update", response_model=BatchUpdateResponse)
async def batch_update_episodes(
    request: BatchUpdateRequest,
) -> BatchUpdateResponse:
    """
    Update properties for multiple episodes in a single request.

    Supports updating: injection_tier, summary, trigger_task_types, pinned, auto_inject, display_order.
    Only provided fields are updated (partial update).

    This is the primary batch update endpoint for import operations.

    Example request:
    ```json
    {
        "updates": [
            {"uuid": "abc12345", "summary": "use dt for tests", "trigger_task_types": ["testing"]},
            {"uuid": "def67890", "injection_tier": "mandate", "pinned": true}
        ]
    }
    ```
    """
    from app.services.memory.graphiti_client import batch_update_episode_properties

    results: list[BatchUpdateResult] = []
    resolved_updates: list[dict[str, Any]] = []
    resolution_errors: dict[str, str] = {}

    for item in request.updates:
        try:
            full_uuid = await resolve_uuid_prefix(item.uuid, group_id="global")
            update_dict: dict[str, Any] = {"uuid": full_uuid}

            if item.injection_tier is not None:
                update_dict["injection_tier"] = item.injection_tier.value
            if item.summary is not None:
                update_dict["summary"] = item.summary
            if item.trigger_task_types is not None:
                update_dict["trigger_task_types"] = item.trigger_task_types
            if item.pinned is not None:
                update_dict["pinned"] = item.pinned
            if item.auto_inject is not None:
                update_dict["auto_inject"] = item.auto_inject
            if item.display_order is not None:
                update_dict["display_order"] = item.display_order

            resolved_updates.append(update_dict)
        except ValueError as e:
            resolution_errors[item.uuid] = str(e)

    if resolved_updates:
        update_results = await batch_update_episode_properties(resolved_updates)
        for update_dict in resolved_updates:
            full_uuid = update_dict["uuid"]
            results.append(
                BatchUpdateResult(
                    uuid=full_uuid,
                    success=update_results.get(full_uuid, False),
                    error=None if update_results.get(full_uuid) else "Episode not found",
                )
            )

    for uuid, error in resolution_errors.items():
        results.append(BatchUpdateResult(uuid=uuid, success=False, error=error))

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
    """
    Clean up memories not accessed within TTL period.

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
        raise HTTPException(
            status_code=500,
            detail=f"Cleanup failed: {e}",
        ) from e


@router.post("/cleanup-orphaned", response_model=OrphanedCleanupResponse)
async def cleanup_orphaned_edges() -> OrphanedCleanupResponse:
    """
    Clean up edges with stale episode references.

    Graphiti's remove_episode only removes edges where the deleted episode
    is the FIRST in the episodes[] list. This cleanup handles orphaned
    edges left behind when episodes are deleted.

    This operation:
    1. Finds edges with episode references that no longer exist
    2. Removes stale episode UUIDs from edges
    3. Deletes edges where all episodes have been removed
    """
    from app.services.memory import get_memory_service
    from app.services.memory.service import MemoryScope

    try:
        memory = get_memory_service(MemoryScope.GLOBAL, None)
        result = await memory.cleanup_orphaned_edges()
        return OrphanedCleanupResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Orphaned cleanup failed: {e}",
        ) from e
