"""Memory Episodes - Core CRUD handler functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from app.services.memory import MemoryService
from app.services.memory.episode_creator import get_episode_creator

if TYPE_CHECKING:
    from .memory_schemas import (
        AddEpisodeRequest,
        AddEpisodeResponse,
        DeleteEpisodeResponse,
        EpisodeDetailResponse,
        UpdateEpisodePropertiesRequest,
        UpdateEpisodePropertiesResponse,
    )


async def handle_add_episode(
    request: AddEpisodeRequest,
    memory: MemoryService,
) -> AddEpisodeResponse:
    """Add an episode to the knowledge graph memory."""
    from graphiti_core.utils.datetime_utils import utc_now

    from app.services.memory.ingestion_config import LEARNING

    from .memory_schemas import AddEpisodeResponse

    creator = get_episode_creator(scope=memory.scope, scope_id=memory.scope_id)
    result = await creator.create(
        content=request.content,
        name=f"{request.source.value}_{utc_now().isoformat()}",
        config=LEARNING,
        source_description=request.source_description,
        reference_time=request.reference_time,
        source=request.source,
    )
    if not result.success:
        raise HTTPException(
            status_code=500, detail=f"Failed to add episode: {result.validation_error}"
        )

    new_uuid = result.uuid or ""

    # Set injection tier if specified
    if request.injection_tier and new_uuid:
        from app.services.memory.graphiti_client import set_episode_injection_tier

        await set_episode_injection_tier(new_uuid, request.injection_tier.value)

    # Copy stats from source episode if requested
    if request.preserve_stats_from and new_uuid:
        from app.services.memory.graphiti_client import copy_episode_stats

        await copy_episode_stats(request.preserve_stats_from, new_uuid)

    return AddEpisodeResponse(uuid=new_uuid)


async def handle_get_episode(
    full_uuid: str,
    memory: MemoryService,
) -> EpisodeDetailResponse:
    """Get detailed information about a single episode."""
    from .memory_schemas import EpisodeDetailResponse

    result = await memory.get_episode(full_uuid)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
    return EpisodeDetailResponse(**result)


async def handle_delete_episode(
    full_uuid: str,
    memory: MemoryService,
) -> DeleteEpisodeResponse:
    """Delete an episode from memory."""
    from .memory_schemas import DeleteEpisodeResponse

    try:
        await memory.delete_episode(full_uuid)
        return DeleteEpisodeResponse(
            success=True,
            episode_id=full_uuid,
            message="Episode deleted successfully",
        )
    except Exception as e:
        raise HTTPException(
            status_code=404 if "not found" in str(e).lower() else 500,
            detail=f"Failed to delete episode: {e}",
        ) from e


async def handle_update_episode_properties(
    full_uuid: str,
    request: UpdateEpisodePropertiesRequest,
) -> UpdateEpisodePropertiesResponse:
    """Update episode properties (pinned, auto_inject, display_order, triggers, summary)."""
    from app.services.memory.graphiti_client import (
        set_episode_auto_inject,
        set_episode_display_order,
        set_episode_pinned,
        set_episode_summary,
        set_episode_trigger_phases,
        set_episode_trigger_task_types,
    )

    from .memory_schemas import UpdateEpisodePropertiesResponse

    try:
        messages: list[str] = []
        final_pinned = None
        final_auto_inject = None
        final_display_order = None
        final_trigger_task_types = None
        final_trigger_phases = None
        final_summary = None

        if request.pinned is not None:
            success = await set_episode_pinned(full_uuid, request.pinned)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_pinned = request.pinned
            messages.append(f"pinned={request.pinned}")

        if request.auto_inject is not None:
            success = await set_episode_auto_inject(full_uuid, request.auto_inject)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_auto_inject = request.auto_inject
            messages.append(f"auto_inject={request.auto_inject}")

        if request.display_order is not None:
            success = await set_episode_display_order(full_uuid, request.display_order)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_display_order = request.display_order
            messages.append(f"display_order={request.display_order}")

        if request.trigger_task_types is not None:
            success = await set_episode_trigger_task_types(full_uuid, request.trigger_task_types)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_trigger_task_types = request.trigger_task_types
            messages.append(f"trigger_task_types={request.trigger_task_types}")

        if request.trigger_phases is not None:
            success = await set_episode_trigger_phases(full_uuid, request.trigger_phases)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_trigger_phases = request.trigger_phases
            messages.append(f"trigger_phases={request.trigger_phases}")

        if request.summary is not None:
            success = await set_episode_summary(full_uuid, request.summary)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_summary = request.summary
            messages.append(f"summary={request.summary}")

        if not messages:
            raise HTTPException(status_code=400, detail="No properties to update")

        return UpdateEpisodePropertiesResponse(
            success=True,
            episode_id=full_uuid,
            pinned=final_pinned,
            auto_inject=final_auto_inject,
            display_order=final_display_order,
            trigger_task_types=final_trigger_task_types,
            trigger_phases=final_trigger_phases,
            summary=final_summary,
            message=f"Updated: {', '.join(messages)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update properties: {e}") from e
