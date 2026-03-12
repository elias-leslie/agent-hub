"""Post-heartbeat lifecycle — guaranteed summaries and format validation.

Runs after complete_internal() returns, ensuring outcomes that Jenny's voluntary
behavior alone cannot guarantee.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.workflows._completion_review import CompletionReviewOutcome, review_persona_completion
from app.workflows._session_postprocess import (
    ensure_session_summary as _shared_ensure_session_summary,
)
from app.workflows._session_postprocess import (
    extract_synthetic_summary as _shared_extract_synthetic_summary,
)

if TYPE_CHECKING:
    from app.api.complete.types import CompletionInternalResult

logger = logging.getLogger(__name__)


async def postprocess_heartbeat(
    result: CompletionInternalResult,
    interval_minutes: int,
    target_project_id: str | None = None,
):
    """Post-process heartbeat: summaries, format validation, metrics.

    Returns a HeartbeatResult instance.
    """
    from app.workflows.persona_heartbeat import HeartbeatResult

    content = result.content or ""
    session_id = result.session_id

    # 1. Summary extraction
    summary_stored = await _ensure_session_summary(session_id, content)

    # 2. Format validation
    status, format_ok = _validate_heartbeat_format(content)

    # 3. Record observability metrics
    from app.workflows._heartbeat_redis import record_heartbeat_metrics

    await record_heartbeat_metrics(
        session_id=session_id,
        format_compliant=format_ok,
        summary_stored=summary_stored,
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        had_error=result.error is not None,
    )

    # 4. Retry MCP tools that failed with "Stream closed"
    mcp_retried = await _retry_failed_mcp_tools(session_id)
    cleanup_status = await _get_cleanup_status_summary()
    workstream_inventory = await _get_workstream_inventory()
    completion_review = await _maybe_review_completion(
        content=content,
        session_id=session_id,
        target_project_id=target_project_id,
        cleanup_status=cleanup_status,
        workstream_inventory=workstream_inventory,
    )
    followup_reason = _detect_followup_reason(content, cleanup_status, workstream_inventory)
    followup_note = None
    if followup_reason is None and completion_review and completion_review.used:
        if completion_review.decision == "continue":
            followup_reason = "completion_review_continue"
            followup_note = completion_review.reason
        elif completion_review.decision == "escalate":
            followup_reason = "completion_review_escalate"
            followup_note = completion_review.reason
    followup_dispatched = False
    if followup_reason:
        followup_dispatched = await _dispatch_followup_wake(
            followup_reason,
            target_project_id,
            note=followup_note,
            parent_session_id=session_id,
        )

    return HeartbeatResult(
        status=status,
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        interval_minutes=interval_minutes,
        error=result.error,
        format_compliant=format_ok,
        summary_stored=summary_stored,
        mcp_retried=mcp_retried,
        followup_dispatched=followup_dispatched,
        followup_reason=followup_reason,
        completion_review_used=bool(completion_review and completion_review.used),
        completion_review_decision=completion_review.decision if completion_review else None,
        completion_review_reason=completion_review.reason if completion_review else None,
        completion_review_session_id=completion_review.session_id if completion_review else None,
        completion_review_agent_slug=completion_review.reviewer_agent_slug if completion_review else None,
        completion_review_model_id=completion_review.reviewer_model_id if completion_review else None,
    )


async def _ensure_session_summary(session_id: str, content: str) -> bool:
    """Ensure the session has a summary — from inline tags or synthetic fallback."""
    return await _shared_ensure_session_summary(
        session_id,
        content,
        agent_id="persona",
        empty_fallback="Heartbeat completed (no output)",
    )


def _extract_synthetic_summary(content: str) -> str:
    """Extract a synthetic summary from heartbeat output.

    Parses HEARTBEAT_OK/HEARTBEAT_ACTION prefix and extracts the sentence after it.
    Falls back to first 120 chars of content.
    """
    return _shared_extract_synthetic_summary(content)



def _validate_heartbeat_format(content: str) -> tuple[str, bool]:
    """Validate heartbeat output format.

    Returns (status, format_compliant):
    - HEARTBEAT_OK → ("success", True)
    - HEARTBEAT_ACTION → ("action", True)
    - Anything else → ("success", False) with a warning
    """
    if not content:
        return "success", False

    # Multi-turn heartbeats place the prefix in the final message,
    # not at the start of the concatenated content.
    if "HEARTBEAT_OK" in content:
        return "success", True
    if "HEARTBEAT_ACTION" in content:
        return "action", True

    logger.warning("Heartbeat output missing format prefix: %.60s...", content.strip()[:60])
    return "success", False


async def _get_cleanup_status_summary() -> str:
    from app.workflows._heartbeat_data import _get_cleanup_status_summary as fetch_cleanup_status

    return await fetch_cleanup_status()


async def _get_workstream_inventory() -> str:
    from app.workflows._heartbeat_data import (
        _get_workstream_inventory as fetch_workstream_inventory,
    )

    return await fetch_workstream_inventory()


def _detect_followup_reason(
    content: str,
    cleanup_status: str,
    workstream_inventory: str,
) -> str | None:
    if "HEARTBEAT_OK" not in (content or ""):
        return None
    if "ACTIONABLE-CLEANUP[" in cleanup_status:
        return "cleanup_actionable"
    if "state=stale_running_task" in workstream_inventory:
        return "stale_running_task"
    if "state=completed_ready_for_closure" in workstream_inventory:
        return "completed_ready_for_closure"
    return None


async def _maybe_review_completion(
    *,
    content: str,
    session_id: str,
    target_project_id: str | None,
    cleanup_status: str,
    workstream_inventory: str,
) -> CompletionReviewOutcome | None:
    if "HEARTBEAT_OK" not in (content or ""):
        return None
    if _detect_followup_reason(content, cleanup_status, workstream_inventory):
        return None
    return await review_persona_completion(
        project_id=target_project_id or "persona-sandbox",
        completion_content=content,
        cleanup_status=cleanup_status,
        workstream_inventory=workstream_inventory,
        parent_session_id=session_id,
    )


def _build_followup_prompt(reason: str, note: str | None = None) -> str:
    detail = f"\nReviewer note: {note}\n" if note else "\n"
    return (
        "The previous heartbeat ended with HEARTBEAT_OK, but a post-run check still showed "
        f"obvious unresolved canonical residue: {reason}.{detail}\n"
        "Re-check only that residue chain and do the concrete next step if it is still valid. "
        "If it is no longer actionable, say why. Do not start speculative new work, model review, "
        "or broad exploration."
    )


async def _dispatch_followup_wake(
    reason: str,
    target_project_id: str | None = None,
    *,
    note: str | None = None,
    parent_session_id: str | None = None,
) -> bool:
    from app.db import async_session
    from app.workflows.persona_heartbeat import HEARTBEAT_PROJECT, _resolve_persona
    from app.workflows.persona_wake import dispatch_wake

    async with async_session() as db:
        model, provider, temperature, thinking_level, _, _ = await _resolve_persona(
            db,
            project_id=target_project_id or HEARTBEAT_PROJECT,
        )

    dispatch_wake(
        agent_slug="persona",
        model=model,
        provider=provider,
        temperature=temperature,
        prompt=_build_followup_prompt(reason, note=note),
        project_id=target_project_id or HEARTBEAT_PROJECT,
        event_type="heartbeat_completion_review" if reason.startswith("completion_review_") else "heartbeat_followup",
        thinking_level=thinking_level,
        parent_session_id=parent_session_id,
    )
    return True


# Tools that can be safely retried by calling the Python function directly.
# Keys are MCP tool names as stored in session_events (mcp__agent-hub__ prefix).
_RETRYABLE_TOOLS: set[str] = {
    "mcp__agent-hub__log_agent_performance",
    "mcp__agent-hub__dispatch_agent",
}


async def _query_stream_closed_failures(session_id: str) -> list:
    """Query session_events for tool_result rows that failed with 'Stream closed'."""
    from sqlalchemy import text

    from app.db import async_session

    async with async_session() as db:
        result = await db.execute(
            text(
                "SELECT se.tool_name, se.sequence FROM session_events se"
                " WHERE se.session_id = :sid AND se.event_type = 'tool_result'"
                " AND (se.tool_output->>'content' = 'Stream closed'"
                "  OR se.content = 'Stream closed')"
                " ORDER BY se.sequence"
            ),
            {"sid": session_id},
        )
        return list(result.fetchall())


async def _fetch_tool_args(session_id: str, tool_name: str, seq: int) -> dict | None:
    """Return the tool_input dict for the tool_use event that preceded *seq*, or None."""
    import json

    from sqlalchemy import text

    from app.db import async_session

    async with async_session() as db:
        use_result = await db.execute(
            text(
                "SELECT tool_input FROM session_events"
                " WHERE session_id = :sid AND event_type = 'tool_use'"
                " AND tool_name = :tool AND sequence < :seq"
                " ORDER BY sequence DESC LIMIT 1"
            ),
            {"sid": session_id, "tool": tool_name, "seq": seq},
        )
        row = use_result.fetchone()

    if not row or not row.tool_input:
        logger.warning("No tool_use args found for %s retry (session=%s)", tool_name, session_id)
        return None

    return row.tool_input if isinstance(row.tool_input, dict) else json.loads(row.tool_input)


async def _execute_tool_retry(tool_name: str, tool_args: dict) -> None:
    """Call the Python function that backs *tool_name* with *tool_args*."""
    if tool_name == "mcp__agent-hub__log_agent_performance":
        from app.services.tools._executor_performance import log_agent_performance

        await log_agent_performance(**tool_args)
    elif tool_name == "mcp__agent-hub__dispatch_agent":
        from app.services.tools._executor_consultation import dispatch_agent

        await dispatch_agent(
            project_id=tool_args.get("project_id"),
            agent_slug=tool_args.get("agent_slug", ""),
            task=tool_args.get("task", ""),
            max_turns=tool_args.get("max_turns", 25),
        )


async def _retry_single_tool(session_id: str, tool_name: str, seq: int) -> bool:
    """Retry one failed MCP tool call. Returns True on success."""
    if tool_name not in _RETRYABLE_TOOLS:
        logger.warning(
            "MCP 'Stream closed' for non-retryable tool %s (session=%s, seq=%d)",
            tool_name, session_id, seq,
        )
        return False

    tool_args = await _fetch_tool_args(session_id, tool_name, seq)
    if tool_args is None:
        return False

    try:
        await _execute_tool_retry(tool_name, tool_args)
        logger.info("MCP retry succeeded: %s (session=%s)", tool_name, session_id)
        return True
    except Exception:
        logger.exception("MCP retry failed: %s (session=%s)", tool_name, session_id)
        return False


async def _retry_failed_mcp_tools(session_id: str) -> int:
    """Retry MCP tools that failed with 'Stream closed'. Returns count retried."""
    try:
        failures = await _query_stream_closed_failures(session_id)
        if not failures:
            return 0
        results = [await _retry_single_tool(session_id, tool_name, seq) for tool_name, seq in failures]
        return sum(results)
    except Exception:
        logger.exception("_retry_failed_mcp_tools failed for session %s", session_id)
        return 0


__all__ = [
    "postprocess_heartbeat",
]
