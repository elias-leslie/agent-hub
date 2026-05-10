"""Memory Episodes - Core CRUD handler functions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException

from app.services.memory import MemoryService
from app.services.memory.repository import get_memory_repository

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .memory_schemas import (
        AddEpisodeRequest,
        AddEpisodeResponse,
        DeleteEpisodeResponse,
        EpisodeDetailResponse,
        MemoryRestoreRequest,
        MemoryRevisionListResponse,
        MemoryRevisionResponse,
        UpdateEpisodePropertiesRequest,
        UpdateEpisodePropertiesResponse,
        UpdateEpisodeRequest,
        UpdateEpisodeResponse,
    )


async def handle_add_episode(
    request: AddEpisodeRequest,
    memory: MemoryService,
) -> AddEpisodeResponse:
    """Add an episode to semantic memory."""
    from datetime import UTC, datetime

    from app.services.memory.enrichment import enrich_memory_content
    from app.services.memory.episode_creator import get_episode_creator
    from app.services.memory.ingestion_config import LEARNING

    from .memory_schemas import AddEpisodeResponse

    creator = get_episode_creator(scope=memory.scope, scope_id=memory.scope_id)
    enrichment = enrich_memory_content(
        request.content,
        source=request.source.value,
        summary=None,
    )
    result = await creator.create(
        content=request.content,
        name=f"{request.source.value}_{datetime.now(UTC).isoformat()}",
        config=LEARNING,
        source_description=request.source_description,
        reference_time=request.reference_time,
        source=request.source,
        context_kind=request.context_kind.value if request.context_kind is not None else None,
        applicability=(
            request.applicability.model_dump() if request.applicability is not None else None
        ),
        summary=enrichment.summary,
        metadata=enrichment.metadata,
        sensitivity_tier=enrichment.sensitivity_tier,
        changed_by="api",
        change_reason=request.change_reason or "Episode added",
        bypass_compactness=request.bypass_compactness,
    )
    if not result.success:
        # Validation failures (Caveman gate, verbose patterns, etc.) are user
        # input errors — return 422 so the UI can surface the message and
        # offer the bypass_compactness override.
        message = result.validation_error or "Failed to add episode"
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_error",
                "message": message,
                "details": [{"message": message}],
            },
        )

    new_uuid = result.uuid or ""
    await _maybe_set_injection_tier(new_uuid, request)
    await _maybe_copy_stats(new_uuid, request)
    return AddEpisodeResponse(uuid=new_uuid)


async def _maybe_set_injection_tier(new_uuid: str, request: AddEpisodeRequest) -> None:
    """Set injection tier on new episode if requested."""
    if request.injection_tier and new_uuid:
        from app.services.memory.episode_property_setters import set_episode_injection_tier

        await set_episode_injection_tier(new_uuid, request.injection_tier.value)


async def _maybe_copy_stats(new_uuid: str, request: AddEpisodeRequest) -> None:
    """Copy stats from source episode if requested."""
    if request.preserve_stats_from and new_uuid:
        from app.services.memory.episode_properties import copy_episode_stats

        await copy_episode_stats(request.preserve_stats_from, new_uuid)


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
    change_reason: str | None = None,
) -> DeleteEpisodeResponse:
    """Delete an episode from memory."""
    from .memory_schemas import DeleteEpisodeResponse

    try:
        await memory.delete_episode(
            full_uuid,
            changed_by="api",
            change_reason=change_reason,
        )
        return DeleteEpisodeResponse(
            success=True,
            episode_id=full_uuid,
            message="Episode deleted successfully",
            revision_id=None,
        )
    except Exception as e:
        logger.exception("Failed to delete episode %s", full_uuid)
        raise HTTPException(
            status_code=404 if "not found" in str(e).lower() else 500,
            detail=f"Failed to delete episode: {e}",
        ) from e


async def handle_update_episode_properties(
    full_uuid: str,
    request: UpdateEpisodePropertiesRequest,
) -> UpdateEpisodePropertiesResponse:
    """Update episode properties (pinned, auto_inject, display_order, triggers, summary)."""
    from ._memory_episodes_helpers import apply_episode_properties
    from .memory_schemas import UpdateEpisodePropertiesResponse

    try:
        finals, messages = await apply_episode_properties(full_uuid, request)

        if not messages:
            raise HTTPException(status_code=400, detail="No properties to update")

        episode = await get_memory_repository().get_as_dict(full_uuid)
        version = (
            int(episode["version"])
            if isinstance(episode, dict) and episode.get("version") is not None
            else None
        )

        return UpdateEpisodePropertiesResponse(
            success=True,
            episode_id=full_uuid,
            pinned=finals["final_pinned"],
            auto_inject=finals["final_auto_inject"],
            display_order=finals["final_display_order"],
            trigger_task_types=finals["final_trigger_task_types"],
            trigger_phases=finals["final_trigger_phases"],
            context_kind=finals["final_context_kind"],
            applicability=finals["final_applicability"],
            summary=finals["final_summary"],
            render_mode=finals["final_render_mode"],
            message=f"Updated: {', '.join(messages)}",
            version=version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update properties for %s", full_uuid)
        raise HTTPException(status_code=500, detail=f"Failed to update properties: {e}") from e


async def handle_update_episode(
    full_uuid: str,
    request: UpdateEpisodeRequest,
) -> UpdateEpisodeResponse:
    """Update episode content and/or tier without rotating UUID."""
    from ._memory_episodes_helpers import build_episode_updates
    from .memory_schemas import UpdateEpisodeResponse

    if request.content is None and request.injection_tier is None:
        raise HTTPException(status_code=400, detail="No fields to update")

    repo = get_memory_repository()

    try:
        updates, messages = await build_episode_updates(full_uuid, request, repo)
        update_kwargs = dict(updates)
        update_kwargs["changed_by"] = "api"
        if request.change_reason is not None:
            update_kwargs["change_reason"] = request.change_reason
        success = await repo.update(full_uuid, **update_kwargs)
        if not success:
            raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
        episode = await repo.get_as_dict(full_uuid)
        version = (
            int(episode["version"])
            if isinstance(episode, dict) and episode.get("version") is not None
            else None
        )
        return UpdateEpisodeResponse(
            success=True,
            episode_id=full_uuid,
            injection_tier=request.injection_tier.value if request.injection_tier is not None else None,
            message=f"Updated: {', '.join(messages)}",
            version=version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update episode %s", full_uuid)
        raise HTTPException(status_code=500, detail=f"Failed to update episode: {e}") from e


def _revision_to_response(revision: object) -> MemoryRevisionResponse:
    from app.models.memory_unified import MemoryRevision

    from .memory_schemas import MemoryRevisionResponse

    assert isinstance(revision, MemoryRevision)
    return MemoryRevisionResponse(
        id=revision.id,
        memory_id=str(revision.memory_id) if revision.memory_id else None,
        memory_uuid=revision.memory_uuid,
        version=revision.version,
        action=revision.action,
        content=revision.content,
        name=revision.name,
        summary=revision.summary,
        injection_tier={1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}.get(
            revision.tier, "reference"
        ),
        scope=revision.scope,
        scope_id=revision.scope_id,
        tags=list(revision.tags or []),
        changed_by=revision.changed_by,
        change_reason=revision.change_reason,
        content_hash=revision.content_hash,
        created_at=revision.created_at,
    )


async def resolve_episode_or_revision_uuid(episode_id: str) -> str:
    """Resolve an episode UUID prefix against active rows first, then revisions."""
    repo = get_memory_repository()
    try:
        return await repo.resolve_uuid_prefix(episode_id)
    except ValueError:
        try:
            return await repo.resolve_revision_memory_uuid_prefix(episode_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


async def handle_list_episode_revisions(
    episode_id: str,
    *,
    limit: int = 20,
) -> MemoryRevisionListResponse:
    """List immutable revision history for one memory episode."""
    from .memory_schemas import MemoryRevisionListResponse

    full_uuid = await resolve_episode_or_revision_uuid(episode_id)
    repo = get_memory_repository()
    revisions = await repo.list_revisions(full_uuid, limit=limit)
    return MemoryRevisionListResponse(
        revisions=[_revision_to_response(revision) for revision in revisions],
        total=len(revisions),
    )


async def handle_restore_episode_revision(
    episode_id: str,
    revision_id: str,
    request: MemoryRestoreRequest,
) -> UpdateEpisodeResponse:
    """Restore a memory episode to a previous revision."""
    from .memory_schemas import UpdateEpisodeResponse

    full_uuid = await resolve_episode_or_revision_uuid(episode_id)
    repo = get_memory_repository()
    restored = await repo.restore_revision(
        full_uuid,
        revision_id,
        changed_by="api",
        change_reason=request.change_reason,
    )
    if restored is None:
        raise HTTPException(status_code=404, detail="Memory revision not found")
    return UpdateEpisodeResponse(
        success=True,
        episode_id=full_uuid,
        injection_tier=restored.injection_tier,
        message=f"Restored revision {revision_id}",
        version=restored.version,
    )
