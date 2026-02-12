"""Progressive context building logic for memory agent."""

import logging
import time

from app.services.memory.context_injector import ProgressiveContext
from app.services.memory.service import MemoryScope

from .memory_agent_helpers import build_reference_episodes

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
) -> tuple[ProgressiveContext, str]:
    """Build progressive context and assign variant."""
    from app.services.memory.context_injector import build_progressive_context
    from app.services.memory.variants import assign_variant

    assigned_variant = assign_variant(
        external_id=external_id,
        project_id=project_id or scope_id,
        variant_override=variant_override,
    )

    context = await build_progressive_context(
        query=query,
        scope=scope,
        scope_id=scope_id,
        include_global=include_global,
        task_type=task_type,
        phase=phase,
    )

    context.debug_info["variant"] = assigned_variant.value
    return context, assigned_variant.value


async def build_continuity_markdown(
    scope: MemoryScope,
    scope_id: str | None,
    current_branch: str | None,
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
) -> str:
    """Format context with reference index and prepend continuity."""
    from app.services.memory.context_injector import format_context_with_reference_index

    reference_episodes = await build_reference_episodes(scope, scope_id)
    formatted = format_context_with_reference_index(
        context,
        reference_episodes=reference_episodes,
        include_citations=True,
    )

    continuity_md = await build_continuity_markdown(scope, scope_id, current_branch)
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
            reference_count=len(context.reference),
            total_tokens=context.total_tokens,
            query=query,
            variant=variant,
            session_id=session_id,
            external_id=external_id,
            project_id=project_id or scope_id,
            memories_loaded=loaded_uuids,
        ))
        logger.info(
            "Progressive-context metrics: session=%s external=%s loaded=%d latency=%dms",
            session_id, external_id, len(loaded_uuids), latency_ms,
        )
