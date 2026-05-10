"""Helper functions for memory_episodes_handlers.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .memory_schemas import UpdateEpisodePropertiesRequest


async def _apply_property_setter(
    full_uuid: str,
    setter_coro: Any,
) -> None:
    """Run a property setter coroutine; raise 404 if it returns False."""
    success = await setter_coro
    if not success:
        raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")


async def _apply_scalar_properties(
    full_uuid: str,
    request: UpdateEpisodePropertiesRequest,
    finals: dict[str, Any],
    messages: list[str],
) -> None:
    """Apply pinned, auto_inject, display_order, trigger_*, context_kind."""
    from app.services.memory.episode_property_setters import (
        set_episode_auto_inject,
        set_episode_context_kind,
        set_episode_display_order,
        set_episode_pinned,
        set_episode_render_mode,
        set_episode_trigger_phases,
        set_episode_trigger_task_types,
    )

    cr = request.change_reason

    if request.pinned is not None:
        await _apply_property_setter(full_uuid, set_episode_pinned(full_uuid, request.pinned, change_reason=cr))
        finals["final_pinned"] = request.pinned
        messages.append(f"pinned={request.pinned}")

    if request.auto_inject is not None:
        await _apply_property_setter(full_uuid, set_episode_auto_inject(full_uuid, request.auto_inject, change_reason=cr))
        finals["final_auto_inject"] = request.auto_inject
        messages.append(f"auto_inject={request.auto_inject}")

    if request.display_order is not None:
        await _apply_property_setter(full_uuid, set_episode_display_order(full_uuid, request.display_order, change_reason=cr))
        finals["final_display_order"] = request.display_order
        messages.append(f"display_order={request.display_order}")

    if request.trigger_task_types is not None:
        await _apply_property_setter(full_uuid, set_episode_trigger_task_types(full_uuid, request.trigger_task_types, change_reason=cr))
        finals["final_trigger_task_types"] = request.trigger_task_types
        messages.append(f"trigger_task_types={request.trigger_task_types}")

    if request.trigger_phases is not None:
        await _apply_property_setter(full_uuid, set_episode_trigger_phases(full_uuid, request.trigger_phases, change_reason=cr))
        finals["final_trigger_phases"] = request.trigger_phases
        messages.append(f"trigger_phases={request.trigger_phases}")

    if request.context_kind is not None:
        await _apply_property_setter(full_uuid, set_episode_context_kind(full_uuid, request.context_kind.value, change_reason=cr))
        finals["final_context_kind"] = request.context_kind
        messages.append(f"context_kind={request.context_kind.value}")

    # render_mode uses field-presence detection: explicit null clears the override,
    # field absence leaves it untouched.
    if "render_mode" in request.model_fields_set:
        await _apply_property_setter(
            full_uuid,
            set_episode_render_mode(full_uuid, request.render_mode, change_reason=cr),
        )
        finals["final_render_mode"] = request.render_mode
        messages.append(f"render_mode={request.render_mode or 'auto'}")


async def _apply_complex_properties(
    full_uuid: str,
    request: UpdateEpisodePropertiesRequest,
    finals: dict[str, Any],
    messages: list[str],
) -> None:
    """Apply applicability and summary properties."""
    from app.services.memory.episode_property_setters import (
        set_episode_applicability,
        set_episode_summary,
    )

    cr = request.change_reason

    if request.applicability is not None:
        await _apply_property_setter(full_uuid, set_episode_applicability(full_uuid, request.applicability.model_dump(), change_reason=cr))
        finals["final_applicability"] = request.applicability
        messages.append("applicability")

    if request.summary is not None:
        await _apply_property_setter(full_uuid, set_episode_summary(full_uuid, request.summary, change_reason=cr))
        finals["final_summary"] = request.summary
        messages.append(f"summary={request.summary}")


async def apply_episode_properties(
    full_uuid: str,
    request: UpdateEpisodePropertiesRequest,
) -> tuple[dict[str, Any], list[str]]:
    """Apply all non-None properties from request; return finals dict and message list."""
    finals: dict[str, Any] = {
        "final_pinned": None,
        "final_auto_inject": None,
        "final_display_order": None,
        "final_trigger_task_types": None,
        "final_trigger_phases": None,
        "final_context_kind": None,
        "final_applicability": None,
        "final_summary": None,
        "final_render_mode": None,
    }
    messages: list[str] = []
    await _apply_scalar_properties(full_uuid, request, finals, messages)
    await _apply_complex_properties(full_uuid, request, finals, messages)
    return finals, messages


async def build_episode_updates(
    full_uuid: str,
    request: Any,
    repo: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Build the updates dict and messages list for handle_update_episode."""

    updates: dict[str, Any] = {}
    messages: list[str] = []

    if request.content is not None:
        updates, messages = await _build_content_update(full_uuid, request, repo, updates, messages)

    if request.injection_tier is not None:
        updates["injection_tier"] = request.injection_tier.value
        messages.append(f"injection_tier={request.injection_tier.value}")

    return updates, messages


async def _build_content_update(
    full_uuid: str,
    request: Any,
    repo: Any,
    updates: dict[str, Any],
    messages: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """Validate content and add embedding to updates dict."""
    from datetime import UTC, datetime

    from app.services.memory.embedder import get_embedder
    from app.services.memory.episode_creator_helpers import build_source_quality_metadata
    from app.services.memory.episode_validation import EpisodeValidationError, EpisodeValidator

    existing_episode = await repo.get_as_dict(full_uuid)
    if existing_episode is None:
        raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
    effective_tier = (
        request.injection_tier.value
        if request.injection_tier is not None
        else str(existing_episode.get("injection_tier") or "reference")
    )
    try:
        EpisodeValidator.validate_content(
            request.content,
            tier=effective_tier,
            bypass_compactness=getattr(request, "bypass_compactness", False),
        )
    except EpisodeValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_error",
                "message": e.message,
                "details": [{"message": pattern} for pattern in e.detected_patterns],
            },
        ) from e
    embedder = get_embedder()
    updates["content"] = request.content
    updates["embedding"] = await embedder.embed(request.content)
    updates["metadata"] = build_source_quality_metadata(
        request.content,
        existing_episode.get("metadata"),
        checked_at=datetime.now(UTC),
        tier_name=effective_tier,
        replace_existing=True,
    )
    messages.append("content")
    return updates, messages
