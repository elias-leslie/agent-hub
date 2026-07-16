"""Progressive context building logic for memory agent."""

import logging
import time

from app.services.memory.context_injector import ProgressiveContext
from app.services.memory.service import MemoryScope

logger = logging.getLogger(__name__)


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
            include_cross_project=False,
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
