"""Post-heartbeat lifecycle — guaranteed summaries and format validation.

Runs after complete_internal() returns, ensuring outcomes that Jenny's voluntary
behavior alone cannot guarantee.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.api.complete.types import CompletionInternalResult

logger = logging.getLogger(__name__)


async def postprocess_heartbeat(
    result: CompletionInternalResult,
    interval_minutes: int,
):
    """Post-process heartbeat: summaries, journaling, format validation.

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
        auto_journaled=False,
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        had_error=result.error is not None,
    )

    # 4. Retry MCP tools that failed with "Stream closed"
    mcp_retried = await _retry_failed_mcp_tools(session_id)

    return HeartbeatResult(
        status=status,
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        interval_minutes=interval_minutes,
        error=result.error,
        format_compliant=format_ok,
        summary_stored=summary_stored,
        auto_journaled=False,
        mcp_retried=mcp_retried,
    )


async def _ensure_session_summary(session_id: str, content: str) -> bool:
    """Ensure the session has a summary — from inline tags or synthetic fallback."""
    try:
        from app.api.complete.citation_tracker import track_inline_summaries
        from app.db import async_session

        async with async_session() as db:
            stored = await track_inline_summaries(content, db, session_id, agent_id="persona")

        if stored:
            return True

        # No [[S:...]] tag — generate synthetic summary
        summary = _extract_synthetic_summary(content)
        if not summary:
            # Fallback: always store *something* so summary_oneliner is never NULL
            summary = "Heartbeat completed (no output)"
        from app.services.memory.summary_generator import _store_summary_on_session

        await _store_summary_on_session(
            session_id=session_id,
            summary_oneliner=summary,
            outcome="completed",
            files_touched=[],
            git_digest="",
        )
        return True
    except Exception:
        logger.exception("Failed to ensure session summary for %s", session_id)
        return False


def _extract_synthetic_summary(content: str) -> str:
    """Extract a synthetic summary from heartbeat output.

    Parses HEARTBEAT_OK/HEARTBEAT_ACTION prefix and extracts the sentence after it.
    Falls back to first 120 chars of content.
    """
    if not content or not content.strip():
        return ""

    text = content.strip()

    # Try to extract from HEARTBEAT_OK/HEARTBEAT_ACTION prefix
    for prefix in ("HEARTBEAT_OK", "HEARTBEAT_ACTION"):
        if text.startswith(prefix):
            after = text[len(prefix):].lstrip(" \u2014\u2013-").strip()
            if after:
                # Take first sentence or up to 120 chars
                period_idx = after.find(". ")
                if 0 < period_idx <= 120:
                    return after[: period_idx + 1]
                return after[:120].rstrip() + ("..." if len(after) > 120 else "")
            return prefix.lower().replace("_", " ")

    # Fallback: first 120 chars
    return text[:120].rstrip() + ("..." if len(text) > 120 else "")



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


# Tools that can be safely retried by calling the Python function directly.
# Keys are MCP tool names as stored in session_events (mcp__agent-hub__ prefix).
_RETRYABLE_TOOLS: set[str] = {
    "mcp__agent-hub__log_agent_performance",
    "mcp__agent-hub__dispatch_agent",
}


async def _retry_failed_mcp_tools(session_id: str) -> int:
    """Retry MCP tools that failed with 'Stream closed'.

    Queries session_events for tool_result events with "Stream closed",
    finds the matching tool_use event to get original args, and retries
    known-safe tools by calling the Python function directly.

    Returns the number of tools successfully retried.
    """
    try:
        import json

        from sqlalchemy import text

        from app.db import async_session

        async with async_session() as db:
            # Find all "Stream closed" tool_result events
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
            failures = result.fetchall()

        if not failures:
            return 0

        retried = 0
        for tool_name, seq in failures:
            if tool_name not in _RETRYABLE_TOOLS:
                logger.warning(
                    "MCP 'Stream closed' for non-retryable tool %s (session=%s, seq=%d)",
                    tool_name, session_id, seq,
                )
                continue

            # Find the matching tool_use event to get original args
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
                logger.warning(
                    "No tool_use args found for %s retry (session=%s)",
                    tool_name, session_id,
                )
                continue

            tool_args = row.tool_input if isinstance(row.tool_input, dict) else json.loads(row.tool_input)

            try:
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

                retried += 1
                logger.info(
                    "MCP retry succeeded: %s (session=%s)", tool_name, session_id,
                )
            except Exception:
                logger.exception(
                    "MCP retry failed: %s (session=%s)", tool_name, session_id,
                )

        return retried
    except Exception:
        logger.exception("_retry_failed_mcp_tools failed for session %s", session_id)
        return 0


__all__ = [
    "postprocess_heartbeat",
]
