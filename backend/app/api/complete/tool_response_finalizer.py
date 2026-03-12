"""Unified response finalization for tool execution handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message

from .closeout_policy import (
    append_closeout_turn,
    build_tool_closeout_fallback,
    plan_user_facing_closeout,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession

    from .tool_models import ToolExecutionResult
    from .tool_progress import ProgressTracker

logger = logging.getLogger(__name__)


async def finalize_response(
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    is_new_session: bool,
    model: str,
    provider: str,
    content_parts: list[str],
    thinking_parts: list[str],
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    turn: int,
    tool_calls_count: int,
    finish_reason: str | None,
    tracker: ProgressTracker,
    *,
    adapter: Any,
    base_messages: list[Message],
    temperature: float,
    working_dir: str | None,
    tool_result_summaries: list[str] | None = None,
) -> ToolExecutionResult:
    """Finalize response with shared closeout recovery and fallback policy."""
    from .tool_event_storage import store_assistant_response
    from .tool_result_builder import finalize_result

    agent_slug = getattr(session, "agent_slug", None)
    final_content = "".join(content_parts)
    fallback_used = False
    fallback_reason: str | None = None

    closeout_plan = plan_user_facing_closeout(
        final_content,
        tool_calls_count=tool_calls_count,
        allow_recovery=True,
        recovery_used=False,
        tool_result_summaries=tool_result_summaries,
    )
    if closeout_plan.action == "recover":
        await tracker.report_status(
            turn or 1,
            closeout_plan.progress_status or "closeout_recovery",
            closeout_plan.progress_message
            or "Requesting one final user-facing closeout response",
        )
        recovered_content, recovered_thinking, recovery_failed = await _attempt_closeout_recovery(
            adapter=adapter,
            base_messages=base_messages,
            model=model,
            temperature=temperature,
            working_dir=working_dir,
            initial_content=final_content,
            recovery_prompt=closeout_plan.prompt or "",
        )
        if recovered_thinking:
            thinking_parts.append(recovered_thinking)
        if not recovery_failed and recovered_content is not None:
            final_content = recovered_content

        fallback_plan = plan_user_facing_closeout(
            final_content,
            tool_calls_count=tool_calls_count,
            allow_recovery=False,
            recovery_used=True,
            tool_result_summaries=tool_result_summaries,
        )
        if fallback_plan.action == "fallback":
            fallback_used = True
            fallback_reason = (
                "tool_closeout_recovery_error"
                if recovery_failed
                else fallback_plan.fallback_reason
            )
            final_content = build_tool_closeout_fallback(
                final_content,
                tool_result_summaries or [],
            )
            await tracker.report_status(
                turn or 1,
                fallback_plan.progress_status or "closeout_fallback",
                fallback_plan.progress_message
                or "Using deterministic tool summary after closeout recovery failed",
            )

    thinking_content = "\n".join(thinking_parts) if thinking_parts else None
    thinking_tokens = len(thinking_content) // 4 if thinking_content else None
    estimated_tokens = len(final_content) // 4

    await store_assistant_response(
        db,
        session_id,
        final_content,
        model,
        estimated_tokens,
        agent_id=agent_slug,
    )
    await tracker.report_complete(turn or 1, tool_calls_count)

    return await finalize_result(
        db=db,
        session=session,
        session_id=session_id,
        is_new_session=is_new_session,
        model=model,
        provider=provider,
        content=final_content,
        loaded_memory_uuids=loaded_memory_uuids,
        memory_group_id=memory_group_id,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
        turn=turn or 1,
        tool_calls_count=tool_calls_count,
        finish_reason=finish_reason,
        progress_log=tracker.log,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )


async def _attempt_closeout_recovery(
    *,
    adapter: Any,
    base_messages: list[Message],
    model: str,
    temperature: float,
    working_dir: str | None,
    initial_content: str,
    recovery_prompt: str,
) -> tuple[str | None, str | None, bool]:
    """Request one final text-only closeout turn after tool execution."""
    recovery_messages = list(base_messages)
    recovery_dicts: list[dict[str, str]] = []
    append_closeout_turn(
        recovery_messages,
        recovery_dicts,
        initial_content,
        recovery_prompt,
    )
    try:
        result = await adapter.complete(
            messages=recovery_messages,
            model=model,
            max_tokens=None,
            temperature=temperature,
            working_dir=working_dir,
        )
    except Exception:
        logger.warning("Tool closeout recovery failed", exc_info=True)
        return None, None, True

    if getattr(result, "tool_calls", None):
        logger.warning("Tool closeout recovery attempted to request tools; falling back")
        return result.content, result.thinking_content, True
    return result.content, result.thinking_content, False
