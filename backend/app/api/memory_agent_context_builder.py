"""Progressive context building logic for memory agent."""

import logging
import time

from app.db import async_session
from app.services.memory.context_injector import ProgressiveContext, build_progressive_context
from app.services.memory.service import MemoryScope
from app.services.memory.settings import get_memory_settings
from app.services.memory.variants import assign_variant

logger = logging.getLogger(__name__)


async def build_progressive_context_with_variant(
    query: str,
    scope: MemoryScope,
    scope_id: str | None,
    include_global: bool,
    task_type: str | None,
    phase: str | None,
    variant_override: str | None,
    external_id: str | None,
    project_id: str | None,
    consumer_profile: str | None,
) -> tuple[ProgressiveContext, str]:
    """Build progressive context and assign variant."""
    async with async_session() as db:
        settings = await get_memory_settings(db)
        assigned_variant = assign_variant(
            external_id=external_id,
            project_id=project_id or scope_id,
            variant_override=variant_override,
            active_variant=settings.active_variant,
        )
        variant_value = getattr(assigned_variant, "value", str(assigned_variant))

        context = await build_progressive_context(
            query=query,
            scope=scope,
            scope_id=scope_id,
            include_global=include_global,
            task_type=task_type,
            phase=phase,
            consumer_profile=consumer_profile,
            variant=variant_value,
            db=db,
        )

        # Apply per-profile/per-project tier overrides so the in-process CLI/hook
        # delivery path honors the same UI controls as the runtime-context preview.
        if consumer_profile:
            from app.services.runtime_context import apply_tier_overrides_to_context

            items = (
                list(context.mandates)
                + list(context.guardrails)
                + list(context.reference_index)
                + list(context.reference)
            )
            if items:
                try:
                    await apply_tier_overrides_to_context(
                        db,
                        consumer_profile=consumer_profile,
                        project_id=project_id or scope_id,
                        items=items,
                    )
                except Exception:
                    logger.warning(
                        "Failed to apply runtime tier overrides for profile=%s project=%s",
                        consumer_profile,
                        project_id or scope_id,
                        exc_info=True,
                    )

    context.debug_info["variant"] = variant_value
    return context, variant_value


async def build_continuity_markdown(
    scope: MemoryScope,
    scope_id: str | None,
    current_branch: str | None,
    session_id: str | None = None,
) -> str:
    """Build continuity context markdown for project scope."""
    if scope != MemoryScope.PROJECT or not scope_id:
        return ""

    try:
        from app.services.memory.continuity_injector import build_continuity_context
        from app.services.memory.settings import get_memory_settings

        settings = await get_memory_settings()
        if not settings.continuity_enabled:
            return ""

        continuity_ctx = await build_continuity_context(
            project_id=scope_id,
            current_branch=current_branch,
            max_sessions=settings.continuity_max_sessions,
            exclude_session_id=session_id,
            include_live_sessions=False,
        )

        if continuity_ctx.markdown:
            logger.info(
                "Continuity context for progressive-context: %d sessions",
                continuity_ctx.session_count,
            )
            return continuity_ctx.markdown + "\n\n"
    except Exception as e:
        logger.warning("Failed to build continuity context: %s", e)

    return ""


async def format_context_with_continuity(
    context: ProgressiveContext,
    scope: MemoryScope,
    scope_id: str | None,
    current_branch: str | None,
    session_id: str | None = None,
    consumer_profile: str | None = None,
) -> str:
    """Format context and prepend continuity."""
    selected_reference_uuids = context.get_reference_uuids()
    indexed_reference_uuids = context.get_reference_index_uuids()
    context.debug_info.update(
        {
            "reference_selected_count": len(selected_reference_uuids),
            "reference_selected_uuids": selected_reference_uuids,
            "reference_index_count": len(indexed_reference_uuids),
            "reference_index_uuids": indexed_reference_uuids,
        }
    )
    from app.services.memory.context_injector import format_progressive_context

    formatted = format_progressive_context(
        context,
        include_citations=True,
        consumer_profile=consumer_profile,
    )

    continuity_md = await build_continuity_markdown(
        scope, scope_id, current_branch, session_id=session_id,
    )
    if continuity_md:
        formatted = continuity_md + formatted

    return formatted


async def track_and_record_metrics(
    context: ProgressiveContext,
    variant: str,
    start_time: float,
    query: str,
    session_id: str | None,
    external_id: str | None,
    project_id: str | None,
    scope_id: str | None,
) -> None:
    """Track loaded memories and record injection metrics."""
    from app.services.memory.metrics_collector import InjectionMetrics, record_injection_metrics
    from app.services.memory.usage_tracker import track_loaded_batch

    loaded_uuids = context.get_loaded_uuids()
    if loaded_uuids:
        await track_loaded_batch(loaded_uuids)

    latency_ms = int((time.monotonic() - start_time) * 1000)
    if session_id or external_id:
        record_injection_metrics(InjectionMetrics(
            injection_latency_ms=latency_ms,
            mandates_count=len(context.mandates),
            guardrails_count=len(context.guardrails),
            reference_count=len(context.reference) + len(context.reference_index),
            reference_selected_count=int(
                context.debug_info.get("reference_selected_count", len(context.reference))
            ),
            reference_index_count=int(
                context.debug_info.get("reference_index_count", len(context.reference_index))
            ),
            total_tokens=context.total_tokens,
            query=query,
            variant=variant,
            session_id=session_id,
            external_id=external_id,
            project_id=project_id or scope_id,
            memories_loaded=loaded_uuids,
            reference_selected_uuids=list(
                context.debug_info.get("reference_selected_uuids", [])
            ),
            reference_index_uuids=list(
                context.debug_info.get("reference_index_uuids", [])
            ),
        ))
        logger.info(
            "Progressive-context metrics: session=%s external=%s loaded=%d latency=%dms",
            session_id, external_id, len(loaded_uuids), latency_ms,
        )
