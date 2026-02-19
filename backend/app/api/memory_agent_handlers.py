"""Handler functions for complex memory agent endpoints."""

import time

from app.services.memory.service import MemoryScope

from .memory_agent_context_builder import (
    build_progressive_context_with_variant,
    format_context_with_continuity,
    track_and_record_metrics,
)
from .memory_agent_helpers import build_budget_usage, build_scoring_breakdown
from .memory_agent_learning_saver import save_learning_with_validation
from .memory_agent_schemas import (
    ProgressiveContextBlock,
    ProgressiveContextResponse,
    SaveLearningRequest,
    SaveLearningResponse,
)


def _assemble_context_response(context, formatted, variant, debug) -> ProgressiveContextResponse:
    """Assemble the ProgressiveContextResponse from a built context object."""
    from app.services.memory.context_injector import get_relevance_debug_info

    return ProgressiveContextResponse(
        mandates=ProgressiveContextBlock(
            items=[m.content for m in context.mandates],
            count=len(context.mandates),
        ),
        guardrails=ProgressiveContextBlock(
            items=[g.content for g in context.guardrails],
            count=len(context.guardrails),
        ),
        reference=ProgressiveContextBlock(
            items=[r.content for r in context.reference],
            count=len(context.reference),
        ),
        total_tokens=context.total_tokens,
        formatted=formatted,
        variant=variant,
        debug=get_relevance_debug_info(context) if debug else None,
        scoring_breakdown=build_scoring_breakdown(context) if debug else None,
        budget_usage=build_budget_usage(context),
    )


async def build_progressive_context_response(
    query: str,
    scope: MemoryScope,
    scope_id: str | None,
    debug: bool,
    include_global: bool,
    task_type: str | None,
    phase: str | None = None,
    variant_override: str | None = None,
    external_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    current_branch: str | None = None,
) -> ProgressiveContextResponse:
    """Build progressive context response with all necessary data."""
    start_time = time.monotonic()

    context, variant = await build_progressive_context_with_variant(
        query=query,
        scope=scope,
        scope_id=scope_id,
        include_global=include_global,
        task_type=task_type,
        phase=phase,
        variant_override=variant_override,
        external_id=external_id,
        project_id=project_id,
    )

    formatted = await format_context_with_continuity(
        context=context,
        scope=scope,
        scope_id=scope_id,
        current_branch=current_branch,
    )

    await track_and_record_metrics(
        context=context,
        variant=variant,
        start_time=start_time,
        query=query,
        session_id=session_id,
        external_id=external_id,
        project_id=project_id,
        scope_id=scope_id,
    )

    return _assemble_context_response(context, formatted, variant, debug)


async def handle_save_learning(
    request: SaveLearningRequest,
    scope: MemoryScope,
    scope_id: str | None,
) -> SaveLearningResponse:
    """Handle save learning request with all validation and storage logic."""
    return await save_learning_with_validation(request, scope, scope_id)
